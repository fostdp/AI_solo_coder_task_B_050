"""
MQTT Ingest Service (微服务1)
职责：
  1. 连接 MQTT Broker，订阅传感器上报主题
  2. 解析消息，发布原始数据到 Redis Stream (stream:raw_data)
  3. 可选：直接写入 TimescaleDB（兼容模式）

数据流：MQTT -> Redis Stream:raw_data
"""

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Dict, Optional

from ..config import get_settings
from ..database import get_db_context
from ..streams import RedisStreamManager, parse_stream_message
from sqlalchemy import text

logger = logging.getLogger("mqtt_ingest")
settings = get_settings()


class MQTTIngestService:
    """MQTT 数据接入微服务"""

    def __init__(self, stream_manager: Optional[RedisStreamManager] = None):
        self.stream_mgr = stream_manager
        self.mqtt_client = None
        self._mqtt_connected = False
        self._loop_started = False
        self._raw_stream = settings.REDIS_STREAM_RAW

        self.last_ecn_data: Dict[str, Dict] = {}
        self.last_menv_data: Dict[str, Dict] = {}

    def _init_mqtt_client(self):
        try:
            import paho.mqtt.client as mqtt
            self.mqtt_client = mqtt.Client(
                client_id=f"mqtt_ingest_{int(time.time())}",
                protocol=mqtt.MQTTv311
            )
            if settings.MQTT_USERNAME:
                self.mqtt_client.username_pw_set(
                    settings.MQTT_USERNAME, settings.MQTT_PASSWORD
                )
            self.mqtt_client.on_connect = self._on_connect
            self.mqtt_client.on_message = self._on_message
            self.mqtt_client.on_disconnect = self._on_disconnect
            self._mqtt_connected = False
            self._loop_started = False
        except Exception as e:
            logger.warning(f"MQTT client init failed (ok if no broker): {e}")
            self.mqtt_client = None

    def _check_port_open(self, host: str, port: int, timeout: float = 0.5) -> bool:
        import socket
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((host, int(port)))
            sock.close()
            return result == 0
        except Exception:
            return False

    def connect_and_subscribe(self) -> bool:
        if not self.mqtt_client:
            self._init_mqtt_client()
        if not self.mqtt_client:
            return False
        try:
            host = settings.MQTT_BROKER
            port = int(settings.MQTT_PORT)
            if not self._check_port_open(host, port, timeout=0.5):
                logger.warning(
                    f"MQTT broker {host}:{port} not reachable. "
                    f"Will work via direct HTTP ingest / stream mode."
                )
                return False
            logger.info(f"Connecting to MQTT {host}:{port}")
            self.mqtt_client.connect(host, port, keepalive=120)
            self.mqtt_client.loop_start()
            self._loop_started = True
            time.sleep(0.5)
            return True
        except Exception as e:
            logger.warning(f"MQTT connect failed (ok if no broker): {e}")
            return False

    def disconnect(self):
        if self.mqtt_client and self._loop_started:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
            logger.info("MQTT ingest client disconnected")

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._mqtt_connected = True
            topic = f"{settings.MQTT_TOPIC_PREFIX}/#"
            client.subscribe(topic, qos=1)
            logger.info(f"MQTT ingest connected, subscribed to {topic}")
        else:
            logger.error(f"MQTT connect failed rc={rc}")

    def _on_disconnect(self, client, userdata, rc):
        self._mqtt_connected = False
        logger.warning(f"MQTT ingest disconnected rc={rc}")

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            topic_parts = msg.topic.split("/")
            if len(topic_parts) >= 3:
                sensor_type = topic_parts[-2]
            else:
                sensor_type = payload.get("sensor_type", "unknown")

            asyncio.create_task(self._handle_message(sensor_type, payload))
        except Exception as e:
            logger.error(f"MQTT message handling failed: {e}")

    async def _handle_message(self, sensor_type: str, payload: Dict):
        if payload.get("status") == "malfunction":
            logger.warning(
                f"Sensor {payload.get('sensor_id')} malfunction: "
                f"code={payload.get('error_code')}"
            )
            return

        try:
            artifact_id = payload.get("artifact_id", "")
            ts = payload.get("timestamp")
            report_time = ts or datetime.utcnow().isoformat()

            stream_data = {
                "sensor_type": sensor_type,
                "payload": payload,
                "received_at": datetime.utcnow().isoformat(),
                "report_time": report_time
            }

            if self.stream_mgr:
                msg_id = await self.stream_mgr.publish(self._raw_stream, stream_data)
                if msg_id:
                    logger.debug(
                        f"Published {sensor_type} data from {artifact_id} "
                        f"to stream {self._raw_stream} ({msg_id})"
                    )
            else:
                logger.debug(
                    f"Stream manager not available, skipping stream publish "
                    f"for {sensor_type}/{artifact_id}"
                )

            self._update_cache(sensor_type, artifact_id, payload)

            await self._write_to_db(sensor_type, payload, report_time)

        except Exception as e:
            logger.exception(f"Error handling {sensor_type} data: {e}")

    def _update_cache(self, sensor_type: str, artifact_id: str, payload: Dict):
        if sensor_type == "electrochemical":
            self.last_ecn_data[artifact_id] = {
                "time": datetime.utcnow(),
                "noise_resistance": payload.get("noise_resistance"),
                "pitting_index": payload.get("pitting_index"),
                "std_voltage": payload.get("std_voltage"),
                "std_current": payload.get("std_current"),
                "skewness_voltage": payload.get("skewness_voltage"),
                "kurtosis_voltage": payload.get("kurtosis_voltage")
            }
        elif sensor_type == "microenv":
            self.last_menv_data[artifact_id] = {
                "time": datetime.utcnow(),
                "temperature": payload.get("temperature"),
                "humidity": payload.get("humidity"),
                "chloride_concentration": payload.get("chloride_concentration"),
                "sulfur_dioxide": payload.get("sulfur_dioxide"),
                "nitrogen_oxides": payload.get("nitrogen_oxides")
            }

    async def _write_to_db(self, sensor_type: str, payload: Dict, report_time_str: str):
        try:
            report_time = datetime.fromisoformat(report_time_str)
        except (ValueError, TypeError):
            report_time = datetime.utcnow()

        try:
            async with get_db_context() as db:
                if sensor_type == "electrochemical":
                    stmt = text("""
                        INSERT INTO electrochemical_noise_data (
                            time, sensor_id, artifact_id, voltage_noise, current_noise,
                            sampling_rate, noise_resistance, pitting_index,
                            std_voltage, std_current, skewness_voltage, kurtosis_voltage
                        ) VALUES (
                            :time, :sensor_id, :artifact_id, :voltage_noise, :current_noise,
                            :sampling_rate, :noise_resistance, :pitting_index,
                            :std_voltage, :std_current, :skewness_voltage, :kurtosis_voltage
                        )
                    """)
                    await db.execute(stmt, {
                        "time": report_time,
                        "sensor_id": payload.get("sensor_id"),
                        "artifact_id": payload.get("artifact_id"),
                        "voltage_noise": payload.get("voltage_noise", []),
                        "current_noise": payload.get("current_noise", []),
                        "sampling_rate": payload.get("sampling_rate", 1000),
                        "noise_resistance": payload.get("noise_resistance"),
                        "pitting_index": payload.get("pitting_index"),
                        "std_voltage": payload.get("std_voltage"),
                        "std_current": payload.get("std_current"),
                        "skewness_voltage": payload.get("skewness_voltage"),
                        "kurtosis_voltage": payload.get("kurtosis_voltage")
                    })

                elif sensor_type == "microenv":
                    stmt = text("""
                        INSERT INTO microenvironment_data (
                            time, sensor_id, artifact_id, temperature, humidity,
                            chloride_concentration, sulfur_dioxide, nitrogen_oxides,
                            formaldehyde, voc_total, illuminance, uv_intensity
                        ) VALUES (
                            :time, :sensor_id, :artifact_id, :temperature, :humidity,
                            :chloride_concentration, :sulfur_dioxide, :nitrogen_oxides,
                            :formaldehyde, :voc_total, :illuminance, :uv_intensity
                        )
                    """)
                    await db.execute(stmt, {
                        "time": report_time,
                        "sensor_id": payload.get("sensor_id"),
                        "artifact_id": payload.get("artifact_id"),
                        "temperature": payload.get("temperature"),
                        "humidity": payload.get("humidity"),
                        "chloride_concentration": payload.get("chloride_concentration"),
                        "sulfur_dioxide": payload.get("sulfur_dioxide"),
                        "nitrogen_oxides": payload.get("nitrogen_oxides"),
                        "formaldehyde": payload.get("formaldehyde"),
                        "voc_total": payload.get("voc_total"),
                        "illuminance": payload.get("illuminance"),
                        "uv_intensity": payload.get("uv_intensity")
                    })

                elif sensor_type == "microscope":
                    has_eruption = bool(payload.get("has_rust_eruption"))
                    rust_det = payload.get("rust_detection") or {}
                    stmt = text("""
                        INSERT INTO microscope_images (
                            time, sensor_id, artifact_id, image_path, resolution,
                            magnification, rust_detection, surface_features,
                            has_rust_eruption, confidence_score
                        ) VALUES (
                            :time, :sensor_id, :artifact_id, :image_path, :resolution,
                            :magnification, :rust_detection, :surface_features,
                            :has_rust_eruption, :confidence_score
                        )
                    """)
                    await db.execute(stmt, {
                        "time": report_time,
                        "sensor_id": payload.get("sensor_id"),
                        "artifact_id": payload.get("artifact_id"),
                        "image_path": payload.get("image_path"),
                        "resolution": payload.get("resolution"),
                        "magnification": payload.get("magnification"),
                        "rust_detection": json.dumps(rust_det),
                        "surface_features": json.dumps(payload.get("surface_features") or {}),
                        "has_rust_eruption": has_eruption,
                        "confidence_score": payload.get("confidence_score")
                    })

        except Exception as e:
            logger.warning(f"DB write failed (stream mode, ok): {e}")

    async def ingest_http(self, sensor_type: str, payload: Dict) -> bool:
        """HTTP 注入接口（兼容 REST API）"""
        try:
            await self._handle_message(sensor_type, payload)
            return True
        except Exception as e:
            logger.error(f"HTTP ingest failed: {e}")
            return False

    def get_realtime_data(self, artifact_id: Optional[str] = None) -> Dict:
        result = {}
        aids = (
            [artifact_id] if artifact_id
            else list(self.last_ecn_data.keys()) + list(self.last_menv_data.keys())
        )
        for aid in set(aids):
            result[aid] = {
                "ecn": self.last_ecn_data.get(aid),
                "menv": self.last_menv_data.get(aid)
            }
        return result
