"""
MQTT 数据接入服务
订阅传感器上报主题，解析数据，入库，触发告警检测和模型预测
"""

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Dict, Optional, Callable
from sqlalchemy import text, insert
from sqlalchemy.ext.asyncio import AsyncSession
import numpy as np

from .database import AsyncSessionLocal, get_db_context
from .config import get_settings
from .alerts.dispatcher import (
    dispatcher, AlertMessage, AlertType, AlertSeverity, ALERT_TEMPLATES
)
from .algorithms.wavelet_features import WaveletPacketFeatureExtractor
from .algorithms.rust_prediction_model import RustPredictionModel

logger = logging.getLogger("mqtt_ingestion")
settings = get_settings()


class MQTTDataProcessor:
    def __init__(self):
        self.wavelet_extractor = WaveletPacketFeatureExtractor()
        self.prediction_model = RustPredictionModel()
        self.last_ecn_data: Dict[str, Dict] = {}
        self.last_menv_data: Dict[str, Dict] = {}
        self.artifact_last_prediction: Dict[str, float] = {}
        self.alert_cooldown: Dict[str, float] = {}
        self._init_mqtt_client()

    def _init_mqtt_client(self):
        try:
            import paho.mqtt.client as mqtt
            self.mqtt_client = mqtt.Client(
                client_id=f"backend_processor_{int(time.time())}",
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
            return False
        try:
            host = settings.MQTT_BROKER
            port = int(settings.MQTT_PORT)
            if not self._check_port_open(host, port, timeout=0.5):
                logger.warning(
                    f"MQTT broker {host}:{port} not reachable (port closed). "
                    f"Will still work via direct HTTP ingest. Start broker for live data."
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
            logger.info("MQTT client disconnected")

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._mqtt_connected = True
            topic = f"{settings.MQTT_TOPIC_PREFIX}/#"
            client.subscribe(topic, qos=1)
            logger.info(f"MQTT connected, subscribed to {topic}")
        else:
            logger.error(f"MQTT connect failed rc={rc}")

    def _on_disconnect(self, client, userdata, rc):
        self._mqtt_connected = False
        logger.warning(f"MQTT disconnected rc={rc}")

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            topic_parts = msg.topic.split("/")
            if len(topic_parts) >= 3:
                sensor_type = topic_parts[-2]
            else:
                sensor_type = payload.get("sensor_type", "unknown")

            asyncio.create_task(self.process_message(sensor_type, payload))
        except Exception as e:
            logger.error(f"MQTT message processing failed: {e}")

    async def process_message(self, sensor_type: str, payload: Dict):
        if payload.get("status") == "malfunction":
            logger.warning(
                f"Sensor {payload.get('sensor_id')} malfunction: code={payload.get('error_code')}"
            )
            return

        try:
            if sensor_type == "electrochemical":
                await self._process_ecn(payload)
            elif sensor_type == "microenv":
                await self._process_menv(payload)
            elif sensor_type == "microscope":
                await self._process_microscope(payload)
            else:
                logger.warning(f"Unknown sensor type: {sensor_type}")
        except Exception as e:
            logger.exception(f"Error processing {sensor_type} data: {e}")

    async def _process_ecn(self, payload: Dict):
        sensor_id = payload["sensor_id"]
        artifact_id = payload["artifact_id"]
        ts = payload.get("timestamp")
        report_time = datetime.fromisoformat(ts) if ts else datetime.utcnow()

        self.last_ecn_data[artifact_id] = {
            "time": report_time,
            "noise_resistance": payload.get("noise_resistance"),
            "pitting_index": payload.get("pitting_index"),
            "std_voltage": payload.get("std_voltage"),
            "std_current": payload.get("std_current"),
            "skewness_voltage": payload.get("skewness_voltage"),
            "kurtosis_voltage": payload.get("kurtosis_voltage")
        }

        async with get_db_context() as db:
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
                "sensor_id": sensor_id,
                "artifact_id": artifact_id,
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

        Rn = float(payload.get("noise_resistance", 9999))
        threshold = settings.NOISE_RESISTANCE_THRESHOLD
        if Rn < threshold:
            asyncio.create_task(self._trigger_alert(
                AlertType.RN_LOW,
                artifact_id=artifact_id,
                sensor_id=sensor_id,
                threshold_value=threshold,
                actual_value=Rn,
                unit="Ω·cm²",
                severity=AlertSeverity.CRITICAL if Rn < threshold * 0.5 else AlertSeverity.WARNING
            ))

        await self._maybe_run_prediction(artifact_id, payload)

    async def _process_menv(self, payload: Dict):
        sensor_id = payload["sensor_id"]
        artifact_id = payload["artifact_id"]
        ts = payload.get("timestamp")
        report_time = datetime.fromisoformat(ts) if ts else datetime.utcnow()

        self.last_menv_data[artifact_id] = {
            "time": report_time,
            "temperature": payload.get("temperature"),
            "humidity": payload.get("humidity"),
            "chloride_concentration": payload.get("chloride_concentration"),
            "sulfur_dioxide": payload.get("sulfur_dioxide"),
            "nitrogen_oxides": payload.get("nitrogen_oxides")
        }

        async with get_db_context() as db:
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
                "sensor_id": sensor_id,
                "artifact_id": artifact_id,
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

        Cl = float(payload.get("chloride_concentration") or 0)
        if Cl > settings.CHLORIDE_THRESHOLD:
            asyncio.create_task(self._trigger_alert(
                AlertType.CL_HIGH,
                artifact_id=artifact_id,
                sensor_id=sensor_id,
                threshold_value=settings.CHLORIDE_THRESHOLD,
                actual_value=Cl,
                unit="μg/m³",
                severity=AlertSeverity.EMERGENCY if Cl > 2 * settings.CHLORIDE_THRESHOLD else AlertSeverity.CRITICAL
            ))

        SO2 = float(payload.get("sulfur_dioxide") or 0)
        if SO2 > settings.SULFUR_DIOXIDE_THRESHOLD:
            asyncio.create_task(self._trigger_alert(
                AlertType.SO2_HIGH,
                artifact_id=artifact_id,
                sensor_id=sensor_id,
                threshold_value=settings.SULFUR_DIOXIDE_THRESHOLD,
                actual_value=SO2,
                unit="μg/m³",
                severity=AlertSeverity.WARNING if SO2 < 2 * settings.SULFUR_DIOXIDE_THRESHOLD else AlertSeverity.CRITICAL
            ))

        T = float(payload.get("temperature") or 0)
        if T > settings.TEMPERATURE_HIGH_THRESHOLD:
            asyncio.create_task(self._trigger_alert(
                AlertType.TEMP_HIGH,
                artifact_id=artifact_id,
                sensor_id=sensor_id,
                threshold_value=settings.TEMPERATURE_HIGH_THRESHOLD,
                actual_value=T,
                unit="°C",
                severity=AlertSeverity.INFO
            ))

        RH = float(payload.get("humidity") or 0)
        if RH > settings.HUMIDITY_HIGH_THRESHOLD:
            asyncio.create_task(self._trigger_alert(
                AlertType.HUMIDITY_HIGH,
                artifact_id=artifact_id,
                sensor_id=sensor_id,
                threshold_value=settings.HUMIDITY_HIGH_THRESHOLD,
                actual_value=RH,
                unit="%RH",
                severity=AlertSeverity.WARNING if RH < 80 else AlertSeverity.CRITICAL
            ))

    async def _process_microscope(self, payload: Dict):
        sensor_id = payload["sensor_id"]
        artifact_id = payload["artifact_id"]
        ts = payload.get("timestamp")
        report_time = datetime.fromisoformat(ts) if ts else datetime.utcnow()

        has_eruption = bool(payload.get("has_rust_eruption"))
        rust_det = payload.get("rust_detection") or {}
        area_ratio = rust_det.get("total_area_ratio", 0)

        async with get_db_context() as db:
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
                "sensor_id": sensor_id,
                "artifact_id": artifact_id,
                "image_path": payload.get("image_path"),
                "resolution": payload.get("resolution"),
                "magnification": payload.get("magnification"),
                "rust_detection": json.dumps(rust_det),
                "surface_features": json.dumps(payload.get("surface_features") or {}),
                "has_rust_eruption": has_eruption,
                "confidence_score": payload.get("confidence_score")
            })

        if has_eruption:
            asyncio.create_task(self._trigger_alert(
                AlertType.RUST_ERUPTION,
                artifact_id=artifact_id,
                sensor_id=sensor_id,
                threshold_value=0.5,
                actual_value=float(area_ratio),
                unit="ratio",
                severity=AlertSeverity.EMERGENCY
            ))

            async with get_db_context() as db:
                await db.execute(text("""
                    UPDATE bronze_artifacts SET status = 3, updated_at = NOW()
                    WHERE artifact_id = :aid AND status < 3
                """), {"aid": artifact_id})

    async def _maybe_run_prediction(self, artifact_id: str, ecn_payload: Dict):
        now = time.time()
        last = self.artifact_last_prediction.get(artifact_id, 0)
        if now - last < 3600:
            return
        self.artifact_last_prediction[artifact_id] = now

        menv = self.last_menv_data.get(artifact_id, {})
        if not menv:
            menv = {
                "temperature": 22.0, "humidity": 45.0,
                "chloride_concentration": 1.0, "sulfur_dioxide": 10.0,
                "nitrogen_oxides": 5.0, "formaldehyde": 10.0
            }

        try:
            volt = np.array(ecn_payload.get("voltage_noise") or [0])
            curr = np.array(ecn_payload.get("current_noise") or [0])
            if len(volt) >= 32 and len(curr) >= 32:
                wavelet_features = self.wavelet_extractor.extract(volt, curr)
            else:
                wavelet_features = self._fallback_wavelet_features(ecn_payload)
        except Exception as e:
            logger.warning(f"Wavelet extract failed for {artifact_id}: {e}")
            wavelet_features = self._fallback_wavelet_features(ecn_payload)

        try:
            result = self.prediction_model.predict(
                artifact_id=artifact_id,
                wavelet_features={
                    "statistical_features": wavelet_features.statistical_features,
                    "band_energy_ratios": wavelet_features.band_energy_ratios,
                    "wavelet_entropy": wavelet_features.wavelet_entropy,
                    "noise_resistance": wavelet_features.noise_resistance,
                    "pitting_index": wavelet_features.pitting_index
                },
                microenv_data=menv,
                target_window="24h"
            )

            async with get_db_context() as db:
                stmt = text("""
                    INSERT INTO rust_predictions (
                        artifact_id, model_version, prediction_time, target_window,
                        eruption_probability, risk_level, risk_zone,
                        feature_contributions, model_input
                    ) VALUES (
                        :artifact_id, :model_version, :prediction_time, :target_window,
                        :eruption_probability, :risk_level, :risk_zone,
                        :feature_contributions, :model_input
                    )
                """)
                await db.execute(stmt, {
                    "artifact_id": artifact_id,
                    "model_version": result.model_version,
                    "prediction_time": result.prediction_time,
                    "target_window": result.target_window,
                    "eruption_probability": result.eruption_probability,
                    "risk_level": result.risk_level,
                    "risk_zone": json.dumps(result.risk_zones),
                    "feature_contributions": json.dumps(result.feature_contributions),
                    "model_input": json.dumps({"ecn": ecn_payload.get("sensor_id"),
                                                "menv": menv})
                })

                if result.risk_level >= 3:
                    new_status = 3 if result.risk_level >= 4 else 2
                    await db.execute(text("""
                        UPDATE bronze_artifacts SET status = GREATEST(status, :st), updated_at = NOW()
                        WHERE artifact_id = :aid
                    """), {"st": new_status, "aid": artifact_id})

            if result.risk_level >= 3:
                asyncio.create_task(self._trigger_alert(
                    AlertType.RUST_PREDICTION,
                    artifact_id=artifact_id,
                    sensor_id=ecn_payload.get("sensor_id", ""),
                    threshold_value=0.5,
                    actual_value=result.eruption_probability,
                    unit="probability",
                    severity=AlertSeverity.CRITICAL if result.risk_level >= 4 else AlertSeverity.WARNING,
                    risk_level=result.risk_level
                ))

            logger.info(
                f"Prediction for {artifact_id}: P={result.eruption_probability:.3f}, "
                f"risk_level={result.risk_level}"
            )
        except Exception as e:
            logger.exception(f"Prediction failed for {artifact_id}: {e}")

    def _fallback_wavelet_features(self, ecn_payload: Dict):
        from dataclasses import dataclass

        @dataclass
        class FB:
            statistical_features: dict
            band_energy_ratios: dict
            wavelet_entropy: float
            noise_resistance: float
            pitting_index: float

        Rn = float(ecn_payload.get("noise_resistance", 500))
        Pi = float(ecn_payload.get("pitting_index", 0.5))
        std_v = float(ecn_payload.get("std_voltage") or 1e-5)
        std_i = float(ecn_payload.get("std_current") or 1e-8)

        ratios = {}
        for i in range(20):
            ratios[f"V_aaa{i}_ratio"] = max(0.01, np.random.normal(0.05, 0.01))
            ratios[f"I_aaa{i}_ratio"] = max(0.01, np.random.normal(0.05, 0.01))
        s = sum(ratios.values())
        for k in ratios:
            ratios[k] /= s

        return FB(
            statistical_features={
                "V_mean": 0.0, "V_std": std_v, "V_rms": std_v,
                "V_skew": float(ecn_payload.get("skewness_voltage", 0)),
                "V_kurtosis": float(ecn_payload.get("kurtosis_voltage", 3)),
                "V_peak_to_peak": std_v * 6, "V_cv": 1.0,
                "I_mean": 0.0, "I_std": std_i, "I_rms": std_i,
                "I_skew": 0.0, "I_kurtosis": 3.0,
                "I_peak_to_peak": std_i * 6, "I_cv": 1.0,
                "cross_corr": 0.1
            },
            band_energy_ratios=ratios,
            wavelet_entropy=3.5 + np.random.normal(0, 0.5),
            noise_resistance=Rn,
            pitting_index=Pi
        )

    async def _trigger_alert(
        self,
        alert_type: AlertType,
        artifact_id: str,
        sensor_id: str,
        threshold_value: float,
        actual_value: float,
        unit: str,
        severity: AlertSeverity,
        risk_level: Optional[int] = None
    ):
        key = f"{artifact_id}_{alert_type.value}"
        now = time.time()
        cd = self.alert_cooldown.get(key, 0)
        if now - cd < 900:
            return
        self.alert_cooldown[key] = now

        tpl = ALERT_TEMPLATES.get(alert_type, {})
        description = tpl.get("description", alert_type.value)

        async with get_db_context() as db:
            artifact_row = await db.execute(text("""
                SELECT name FROM bronze_artifacts WHERE artifact_id = :aid
            """), {"aid": artifact_id})
            name_row = artifact_row.fetchone()
            artifact_name = name_row[0] if name_row else artifact_id

            stmt = text("""
                INSERT INTO alerts (
                    artifact_id, sensor_id, alert_type, severity,
                    threshold_value, actual_value, message, alert_time
                ) VALUES (
                    :artifact_id, :sensor_id, :alert_type, :severity,
                    :threshold_value, :actual_value, :message, :alert_time
                ) RETURNING alert_id
            """)
            result = await db.execute(stmt, {
                "artifact_id": artifact_id,
                "sensor_id": sensor_id or None,
                "alert_type": alert_type.value,
                "severity": severity.value,
                "threshold_value": threshold_value,
                "actual_value": actual_value,
                "message": description,
                "alert_time": datetime.utcnow()
            })
            alert_id_row = result.fetchone()
            alert_id = int(alert_id_row[0]) if alert_id_row else 0

        suggestion = dispatcher.build_alert_suggestion(
            alert_type, severity, actual_value, threshold_value
        )
        alert_msg = AlertMessage(
            alert_id=alert_id,
            artifact_id=artifact_id,
            artifact_name=artifact_name,
            alert_type=alert_type,
            severity=severity,
            threshold_value=threshold_value,
            actual_value=actual_value,
            unit=unit,
            message=description,
            alert_time=datetime.utcnow(),
            risk_level=risk_level,
            suggestion=suggestion
        )
        push_result = await dispatcher.dispatch(alert_msg)

        async with get_db_context() as db:
            await db.execute(text("""
                UPDATE alerts SET
                    wecom_sent = :ws,
                    sms_sent = :ss,
                    push_channels = :pc::jsonb
                WHERE alert_id = :aid
            """), {
                "ws": push_result.get("wecom", False),
                "ss": push_result.get("sms", False),
                "pc": json.dumps(push_result),
                "aid": alert_id
            })

        logger.warning(
            f"ALERT #{alert_id} [{alert_type.value} S{severity.value}] "
            f"{artifact_id}: {actual_value:.3f}{unit} vs {threshold_value} "
            f"-> pushed: {push_result}"
        )

    def get_realtime_data(self, artifact_id: Optional[str] = None) -> Dict:
        result = {}
        aids = [artifact_id] if artifact_id else list(self.last_ecn_data.keys()) + list(self.last_menv_data.keys())
        for aid in set(aids):
            result[aid] = {
                "ecn": self.last_ecn_data.get(aid),
                "menv": self.last_menv_data.get(aid)
            }
        return result


data_processor = MQTTDataProcessor()
