"""
MQTT 传感器数据模拟器 v3.0
- 200 件青铜器 × (30 ECN + 50 MENV + 20 MIC) 传感器
- 15 分钟上报间隔（可配置）
- INJECT_PITTING=1 启用点蚀尖峰注入
- INJECT_CL_PEAK=1 启用高 Cl⁻ 浓度尖峰
- PEAK_INTERVAL_HOURS 尖峰注入周期（默认 6 小时）
- loguru 结构化日志
"""

import asyncio
import json
import os
import random
import time
import argparse
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, field
import numpy as np

try:
    from loguru import logger
    LOGURU_AVAILABLE = True
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    logger = logging.getLogger("mqtt_simulator")
    LOGURU_AVAILABLE = False

import paho.mqtt.client as mqtt

if LOGURU_AVAILABLE:
    logger.remove()
    logger.add(
        lambda msg: print(msg, end=""),
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level:<8}</level> | <level>{message}</level>",
    )


@dataclass
class SimulatedSensor:
    sensor_id: str
    sensor_type: str
    artifact_id: str
    base_values: Dict[str, float] = field(default_factory=dict)
    trend_drift: float = 0.0
    risk_level: int = 1
    malfunction_chance: float = 0.002
    last_report: float = 0
    noise_seed: int = 0
    is_pitting_active: bool = False
    pitting_intensity: float = 0.0


@dataclass
class ChloridePeak:
    active: bool = False
    interval_hours: int = 6
    duration_minutes: int = 30
    multiplier: float = 10.0
    last_trigger_time: float = 0.0
    target_artifacts: List[str] = field(default_factory=list)


class MQTTSensorSimulator:
    DYNASTY_NAMES = ["商", "西周", "东周", "春秋", "战国"]
    TYPE_NAMES = ["鼎", "尊", "爵", "斝", "觚", "觯", "卣", "壶", "盘", "匜", "钟", "镈", "戈", "剑", "钺"]

    def __init__(
        self,
        broker: str = "localhost",
        port: int = 1883,
        username: Optional[str] = None,
        password: Optional[str] = None,
        topic_prefix: str = "museum/bronze",
        interval_seconds: int = 900,
        num_artifacts: int = 200,
        include_anomalies: bool = True,
        inject_pitting: bool = False,
        inject_cl_peak: bool = False,
        peak_interval_hours: int = 6,
        seed: int = 42,
    ):
        self.broker = broker
        self.port = port
        self.username = username
        self.password = password
        self.topic_prefix = topic_prefix
        self.interval = interval_seconds
        self.num_artifacts = num_artifacts
        self.include_anomalies = include_anomalies
        self.inject_pitting = inject_pitting
        self.inject_cl_peak = inject_cl_peak
        self.client = None
        self.connected = False
        self.sensors: List[SimulatedSensor] = []
        self.artifact_names: Dict[str, str] = {}
        self.cl_peak = ChloridePeak(
            active=inject_cl_peak,
            interval_hours=peak_interval_hours,
            target_artifacts=[],
        )
        self._cycle_count = 0

        np.random.seed(seed)
        random.seed(seed)
        self._init_artifacts()
        self._init_sensors()
        self._init_injections()

        ecn_count = sum(1 for s in self.sensors if s.sensor_type == "electrochemical")
        menv_count = sum(1 for s in self.sensors if s.sensor_type == "microenv")
        mic_count = sum(1 for s in self.sensors if s.sensor_type == "microscope")
        logger.info(
            f"Initialized {len(self.sensors)} sensors for {self.num_artifacts} artifacts: "
            f"{ecn_count} ECN + {menv_count} MENV + {mic_count} MIC"
        )
        logger.info(f"Injection: pitting={self.inject_pitting}, cl_peak={self.inject_cl_peak}")

    def _init_artifacts(self):
        for i in range(1, self.num_artifacts + 1):
            aid = f"BRZ{i:05d}"
            dynasty = self.DYNASTY_NAMES[(i - 1) % len(self.DYNASTY_NAMES)]
            type_name = self.TYPE_NAMES[(i - 1) % len(self.TYPE_NAMES)]
            self.artifact_names[aid] = f"{dynasty}{type_name}{i:03d}"

    def _init_sensors(self):
        n_ecn = 30
        n_menv = 50
        n_mic = 20

        for i in range(1, n_ecn + 1):
            artifact_idx = i if i <= 10 else (i * 7) % self.num_artifacts + 1
            artifact_idx = min(artifact_idx, self.num_artifacts)
            self.sensors.append(SimulatedSensor(
                sensor_id=f"ECN{i:03d}",
                sensor_type="electrochemical",
                artifact_id=f"BRZ{artifact_idx:05d}",
                base_values={
                    "Rn": random.uniform(300, 800),
                    "std_v": random.uniform(5e-6, 20e-6),
                    "std_i": random.uniform(1e-9, 5e-8),
                },
                noise_seed=i * 13,
            ))

        for i in range(1, n_menv + 1):
            artifact_idx = (i * 4) % self.num_artifacts + 1
            artifact_idx = min(artifact_idx, self.num_artifacts)
            self.sensors.append(SimulatedSensor(
                sensor_id=f"ENV{i:03d}",
                sensor_type="microenv",
                artifact_id=f"BRZ{artifact_idx:05d}",
                base_values={
                    "temperature": random.uniform(20, 24),
                    "humidity": random.uniform(40, 55),
                    "chloride": random.uniform(0.3, 1.5),
                    "sulfur_dioxide": random.uniform(5, 20),
                },
                noise_seed=1000 + i * 17,
            ))

        for i in range(1, n_mic + 1):
            artifact_idx = (i * 10) % self.num_artifacts + 1
            artifact_idx = min(artifact_idx, self.num_artifacts)
            self.sensors.append(SimulatedSensor(
                sensor_id=f"MIC{i:03d}",
                sensor_type="microscope",
                artifact_id=f"BRZ{artifact_idx:05d}",
                base_values={
                    "has_rust": 0,
                    "rust_area": 0.0,
                    "confidence": 0.95,
                },
                noise_seed=2000 + i * 19,
            ))

    def _init_injections(self):
        if self.include_anomalies:
            self._inject_risk_sensors()

        if self.inject_pitting:
            self._inject_pitting_events()

        if self.inject_cl_peak:
            self._init_cl_peak_targets()

    def _inject_risk_sensors(self):
        risk_indices = [2, 7, 12, 18, 25]
        for idx in risk_indices:
            if idx < len(self.sensors) and self.sensors[idx].sensor_type == "electrochemical":
                s = self.sensors[idx]
                s.risk_level = random.randint(2, 4)
                s.base_values["Rn"] = random.uniform(20, 120)
                s.trend_drift = random.uniform(-5, -2)
                logger.info(f"Injected high-risk: {s.sensor_id} -> Rn={s.base_values['Rn']:.1f}Ω·cm²")

        env_risk = [34, 42, 48]
        for idx in env_risk:
            sensor_idx = 30 + idx
            if sensor_idx < 80 and self.sensors[sensor_idx].sensor_type == "microenv":
                s = self.sensors[sensor_idx]
                s.risk_level = 3
                s.base_values["chloride"] = random.uniform(2.5, 8.0)
                s.base_values["humidity"] = random.uniform(60, 75)
                logger.info(f"Injected high-risk env: {s.sensor_id} -> Cl⁻={s.base_values['chloride']:.1f}μg/m³")

        micro_risk = [3, 11]
        for idx in micro_risk:
            sensor_idx = 80 + idx
            if sensor_idx < len(self.sensors):
                s = self.sensors[sensor_idx]
                s.risk_level = 4
                s.base_values["has_rust"] = 1
                s.base_values["rust_area"] = random.uniform(0.05, 0.15)
                logger.info(f"Injected rust eruption: {s.sensor_id}")

    def _inject_pitting_events(self):
        ecn_sensors = [s for s in self.sensors if s.sensor_type == "electrochemical"]
        n_pitting = max(3, len(ecn_sensors) // 10)
        pitting_targets = random.sample(ecn_sensors, min(n_pitting, len(ecn_sensors)))

        for s in pitting_targets:
            s.is_pitting_active = True
            s.pitting_intensity = random.uniform(0.5, 3.0)
            logger.info(
                f"PITTING: {s.sensor_id} ({s.artifact_id}) "
                f"intensity={s.pitting_intensity:.2f}"
            )

    def _init_cl_peak_targets(self):
        n_targets = random.randint(10, 20)
        all_artifacts = list(set(s.artifact_id for s in self.sensors if s.sensor_type == "microenv"))
        self.cl_peak.target_artifacts = random.sample(
            all_artifacts, min(n_targets, len(all_artifacts))
        )
        self.cl_peak.last_trigger_time = 0
        logger.info(
            f"Cl⁻ PEAK: targeting {len(self.cl_peak.target_artifacts)} artifacts, "
            f"interval={self.cl_peak.interval_hours}h, "
            f"multiplier={self.cl_peak.multiplier}x"
        )

    def _is_cl_peak_active(self) -> bool:
        if not self.cl_peak.active:
            return False
        now = time.time()
        interval_s = self.cl_peak.interval_hours * 3600
        duration_s = self.cl_peak.duration_minutes * 60
        elapsed_since_peak = now - self.cl_peak.last_trigger_time

        if self.cl_peak.last_trigger_time == 0 or elapsed_since_peak >= interval_s:
            self.cl_peak.last_trigger_time = now
            logger.warning(
                f"⚡ Cl⁻ PEAK TRIGGERED for {len(self.cl_peak.target_artifacts)} artifacts!"
            )
            return True

        if elapsed_since_peak < duration_s:
            return True

        return False

    def connect(self) -> bool:
        self.client = mqtt.Client(
            client_id=f"simulator_{int(time.time())}",
            protocol=mqtt.MQTTv311,
            clean_session=True,
        )
        if self.username:
            self.client.username_pw_set(self.username, self.password)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_publish = self._on_publish

        try:
            logger.info(f"Connecting to MQTT broker {self.broker}:{self.port}...")
            self.client.connect(self.broker, self.port, keepalive=60)
            self.client.loop_start()
            time.sleep(2)
            return self.connected
        except Exception as e:
            logger.error(f"Failed to connect MQTT broker: {e}")
            return False

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.connected = True
            logger.info("Connected to MQTT broker successfully")
        else:
            logger.error(f"MQTT connection failed, rc={rc}")

    def _on_disconnect(self, client, userdata, rc):
        self.connected = False
        logger.warning(f"Disconnected from MQTT broker, rc={rc}")

    def _on_publish(self, client, userdata, mid):
        pass

    def _generate_ecn_data(self, sensor: SimulatedSensor) -> Dict:
        rng = np.random.RandomState(sensor.noise_seed + int(time.time() // self.interval))

        Rn_base = sensor.base_values["Rn"]
        drift = sensor.trend_drift * (1 + 0.1 * rng.randn())
        Rn = Rn_base + drift * 10
        Rn *= max(0.3, 1 + 0.25 * rng.randn())
        Rn = max(5.0, min(Rn, 5000.0))

        if sensor.risk_level >= 3 and rng.random() < 0.7:
            Rn *= random.uniform(0.3, 0.6)

        if sensor.is_pitting_active and self.inject_pitting:
            pitting_mod = sensor.pitting_intensity * (0.5 + 0.5 * np.sin(2 * np.pi * self._cycle_count / 96))
            Rn *= max(0.1, 1 - pitting_mod * 0.15)

        sampling_rate = 1000
        n_samples = 1024
        t = np.arange(n_samples) / sampling_rate

        freq_components = [0.1, 0.5, 1, 5, 10, 50, 100]
        v_noise = np.zeros(n_samples)
        i_noise = np.zeros(n_samples)

        for freq in freq_components:
            amp_v = sensor.base_values["std_v"] * (1 + 3 / (freq + 0.1)) * 0.1
            amp_i = sensor.base_values["std_i"] * (1 + 3 / (freq + 0.1)) * 0.1
            phase = rng.uniform(0, 2 * np.pi)
            v_noise += amp_v * np.sin(2 * np.pi * freq * t + phase)
            phase = rng.uniform(0, 2 * np.pi)
            i_noise += amp_i * np.sin(2 * np.pi * freq * t + phase)

        v_noise += rng.normal(0, sensor.base_values["std_v"], n_samples)
        i_noise += rng.normal(0, sensor.base_values["std_i"], n_samples)

        if sensor.risk_level >= 2:
            n_transients = rng.poisson(2 + sensor.risk_level * 2)
            for _ in range(n_transients):
                pos = rng.randint(50, n_samples - 50)
                width = rng.randint(5, 30)
                envelope = np.exp(-0.5 * ((np.arange(width) - width / 2) / (width / 4)) ** 2)
                v_noise[pos:pos + width] += envelope * sensor.base_values["std_v"] * rng.uniform(5, 20)
                i_noise[pos:pos + width] += envelope * sensor.base_values["std_i"] * rng.uniform(5, 20)

        if sensor.is_pitting_active and self.inject_pitting:
            n_pits = rng.poisson(sensor.pitting_intensity * 3)
            for _ in range(n_pits):
                pos = rng.randint(10, n_samples - 10)
                width = rng.randint(2, 8)
                amp_factor = sensor.pitting_intensity * rng.uniform(10, 50)
                i_noise[pos:pos + width] += amp_factor * sensor.base_values["std_i"]

        std_v = float(np.std(v_noise))
        std_i = float(np.std(i_noise))

        try:
            from scipy import stats
            skew_v = float(stats.skew(v_noise))
            kurt_v = float(stats.kurtosis(v_noise))
        except ImportError:
            skew_v = 0.0
            kurt_v = 0.0

        pitting = std_i / (abs(np.mean(i_noise)) + 1e-15)

        if sensor.is_pitting_active and self.inject_pitting:
            pitting += sensor.pitting_intensity * rng.uniform(0.5, 2.0)

        result = {
            "timestamp": datetime.now().isoformat(),
            "sensor_id": sensor.sensor_id,
            "artifact_id": sensor.artifact_id,
            "sensor_type": "electrochemical",
            "voltage_noise": v_noise.tolist(),
            "current_noise": i_noise.tolist(),
            "sampling_rate": sampling_rate,
            "sample_count": n_samples,
            "noise_resistance": float(Rn),
            "pitting_index": float(pitting),
            "std_voltage": std_v,
            "std_current": std_i,
            "skewness_voltage": skew_v,
            "kurtosis_voltage": kurt_v,
        }

        if sensor.is_pitting_active and self.inject_pitting:
            result["pitting_injected"] = True
            result["pitting_intensity"] = float(sensor.pitting_intensity)

        return result

    def _generate_menv_data(self, sensor: SimulatedSensor) -> Dict:
        rng = np.random.RandomState(sensor.noise_seed + int(time.time() // self.interval))

        hour = datetime.now().hour
        day_factor = 1 + 0.08 * np.sin(2 * np.pi * (hour - 6) / 24)

        T = sensor.base_values["temperature"] * day_factor
        T += rng.normal(0, 0.3)

        RH = sensor.base_values["humidity"]
        RH += rng.normal(0, 1.5)

        Cl = sensor.base_values["chloride"]
        Cl *= day_factor * (1 + 0.3 * rng.randn())
        Cl = max(0.05, Cl)

        if sensor.risk_level >= 2 and rng.random() < 0.6:
            Cl += rng.uniform(0.5, 3.0)

        cl_peak_active = False
        if self._is_cl_peak_active() and sensor.artifact_id in self.cl_peak.target_artifacts:
            peak_factor = self.cl_peak.multiplier * (0.8 + 0.4 * rng.random())
            Cl *= peak_factor
            cl_peak_active = True

        SO2 = sensor.base_values["sulfur_dioxide"]
        SO2 *= (1 + 0.25 * rng.randn())
        SO2 = max(0.5, SO2)

        if cl_peak_active:
            SO2 *= 2.0

        NOx = SO2 * rng.uniform(0.3, 0.8)
        HCHO = rng.uniform(5, 25)

        result = {
            "timestamp": datetime.now().isoformat(),
            "sensor_id": sensor.sensor_id,
            "artifact_id": sensor.artifact_id,
            "sensor_type": "microenv",
            "temperature": round(float(T), 2),
            "humidity": round(float(RH), 2),
            "chloride_concentration": round(float(Cl), 3),
            "sulfur_dioxide": round(float(SO2), 2),
            "nitrogen_oxides": round(float(NOx), 2),
            "formaldehyde": round(float(HCHO), 2),
            "voc_total": round(float(HCHO + rng.uniform(50, 200)), 2),
            "illuminance": round(float(rng.uniform(50, 150)), 1),
            "uv_intensity": round(float(rng.uniform(0.1, 5.0)), 3),
        }

        if cl_peak_active:
            result["cl_peak_injected"] = True
            result["cl_peak_multiplier"] = round(self.cl_peak.multiplier, 1)

        return result

    def _generate_microscope_data(self, sensor: SimulatedSensor) -> Dict:
        rng = np.random.RandomState(sensor.noise_seed + int(time.time() // self.interval))

        has_rust = bool(sensor.base_values["has_rust"])
        rust_area = sensor.base_values["rust_area"]
        confidence = sensor.base_values["confidence"]

        if not has_rust and sensor.risk_level >= 2 and rng.random() < 0.3:
            has_rust = True
            rust_area = rng.uniform(0.01, 0.05)
            confidence = rng.uniform(0.7, 0.92)

        if self.inject_pitting:
            ecn_for_artifact = [
                s for s in self.sensors
                if s.artifact_id == sensor.artifact_id
                and s.sensor_type == "electrochemical"
                and s.is_pitting_active
            ]
            if ecn_for_artifact and not has_rust and rng.random() < 0.15:
                has_rust = True
                rust_area = rng.uniform(0.005, 0.03)
                confidence = rng.uniform(0.65, 0.88)

        detections = []
        if has_rust:
            n_patches = rng.poisson(3 + sensor.risk_level * 2)
            for i in range(n_patches):
                detections.append({
                    "patch_id": f"P{i+1:02d}",
                    "bbox": {
                        "x": float(rng.uniform(0, 1)),
                        "y": float(rng.uniform(0, 1)),
                        "w": float(0.02 + rust_area * rng.uniform(0.5, 1.5)),
                        "h": float(0.02 + rust_area * rng.uniform(0.5, 1.5)),
                    },
                    "severity": float(rng.uniform(0.4, 1.0) * sensor.risk_level / 4),
                    "type": random.choice(["powdery", "pitting", "crack"]),
                    "confidence": float(rng.uniform(confidence - 0.1, 0.99)),
                })

        return {
            "timestamp": datetime.now().isoformat(),
            "sensor_id": sensor.sensor_id,
            "artifact_id": sensor.artifact_id,
            "sensor_type": "microscope",
            "image_path": f"/data/microscope/{sensor.sensor_id}/{int(time.time())}.jpg",
            "resolution": "1920x1080",
            "magnification": 200.0,
            "rust_detection": {
                "count": len(detections),
                "total_area_ratio": float(sum(d["bbox"]["w"] * d["bbox"]["h"] for d in detections)),
                "patches": detections,
            },
            "surface_features": {
                "roughness": float(rng.uniform(0.1, 0.9)),
                "corrosion_product_color": random.choice(["green", "blue-green", "gray-green", "white"]),
                "has_cracks": bool(rng.random() < 0.1 + sensor.risk_level * 0.05),
            },
            "has_rust_eruption": has_rust,
            "confidence_score": float(confidence),
        }

    def generate_sensor_data(self, sensor: SimulatedSensor) -> Dict:
        if random.random() < sensor.malfunction_chance:
            return {
                "timestamp": datetime.now().isoformat(),
                "sensor_id": sensor.sensor_id,
                "artifact_id": sensor.artifact_id,
                "sensor_type": sensor.sensor_type,
                "status": "malfunction",
                "error_code": random.randint(1, 5),
            }

        if sensor.sensor_type == "electrochemical":
            return self._generate_ecn_data(sensor)
        elif sensor.sensor_type == "microenv":
            return self._generate_menv_data(sensor)
        else:
            return self._generate_microscope_data(sensor)

    def publish_sensor_data(self, sensor: SimulatedSensor, data: Dict) -> bool:
        if not self.connected:
            return False

        topic = f"{self.topic_prefix}/{sensor.sensor_type}/{sensor.sensor_id}"
        payload = json.dumps(data, ensure_ascii=False)

        try:
            result = self.client.publish(topic, payload, qos=1, retain=False)
            return result.rc == mqtt.MQTT_ERR_SUCCESS
        except Exception as e:
            logger.error(f"Publish exception for {sensor.sensor_id}: {e}")
            return False

    async def run(self, duration_minutes: Optional[int] = None):
        if not self.connect():
            logger.error("Cannot run simulator without MQTT connection")
            return

        start_time = time.time()
        end_time = start_time + duration_minutes * 60 if duration_minutes else None

        try:
            while True:
                cycle_start = time.time()
                self._cycle_count += 1

                logger.info(
                    f"Cycle #{self._cycle_count} - "
                    f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | "
                    f"artifacts={self.num_artifacts} sensors={len(self.sensors)}"
                )

                success_count = 0
                cl_peak_count = 0
                pitting_count = 0

                for sensor in self.sensors:
                    data = self.generate_sensor_data(sensor)
                    if self.publish_sensor_data(sensor, data):
                        success_count += 1
                    if data.get("pitting_injected"):
                        pitting_count += 1
                    if data.get("cl_peak_injected"):
                        cl_peak_count += 1
                    await asyncio.sleep(0.01)

                msg = f"Cycle #{self._cycle_count}: {success_count}/{len(self.sensors)} published"
                if pitting_count:
                    msg += f" | pitting={pitting_count}"
                if cl_peak_count:
                    msg += f" | cl_peak={cl_peak_count}"
                logger.info(msg)

                if end_time and time.time() >= end_time:
                    logger.info(f"Reached duration limit of {duration_minutes} minutes")
                    break

                elapsed = time.time() - cycle_start
                sleep_time = max(1.0, self.interval - elapsed)
                logger.info(f"Next cycle in {sleep_time:.0f}s...")

                remaining = sleep_time
                while remaining > 0:
                    chunk = min(remaining, 30.0)
                    await asyncio.sleep(chunk)
                    remaining -= chunk
                    if end_time and time.time() >= end_time:
                        break

        except asyncio.CancelledError:
            logger.info("Simulator cancelled")
        except KeyboardInterrupt:
            logger.info("Simulator stopped")
        finally:
            if self.client:
                self.client.loop_stop()
                self.client.disconnect()
            logger.info("Simulator shutdown complete")


def main():
    parser = argparse.ArgumentParser(description="Bronze Rust MQTT Sensor Simulator v3.0")
    parser.add_argument("--broker", default=os.getenv("MQTT_BROKER", "localhost"))
    parser.add_argument("--port", type=int, default=int(os.getenv("MQTT_PORT", "1883")))
    parser.add_argument("--username", default=None)
    parser.add_argument("--password", default=None)
    parser.add_argument("--topic-prefix", default="museum/bronze")
    parser.add_argument("--interval", type=int, default=int(os.getenv("REPORT_INTERVAL", "900")))
    parser.add_argument("--num-artifacts", type=int, default=int(os.getenv("NUM_ARTIFACTS", "200")))
    parser.add_argument("--fast", action="store_true", help="Fast mode: 10s interval")
    parser.add_argument("--duration", type=int, default=None)
    parser.add_argument("--no-anomalies", action="store_true")
    parser.add_argument("--inject-pitting", action="store_true",
                        default=os.getenv("INJECT_PITTING", "0") == "1",
                        help="Enable pitting injection (INJECT_PITTING=1)")
    parser.add_argument("--inject-cl-peak", action="store_true",
                        default=os.getenv("INJECT_CL_PEAK", "0") == "1",
                        help="Enable Cl⁻ peak injection (INJECT_CL_PEAK=1)")
    parser.add_argument("--peak-interval", type=int,
                        default=int(os.getenv("PEAK_INTERVAL_HOURS", "6")))
    parser.add_argument("--seed", type=int, default=int(os.getenv("SEED", "42")))

    args = parser.parse_args()
    interval = 10 if args.fast else args.interval

    logger.info(
        f"Starting Bronze Rust Simulator v3.0 "
        f"(interval={interval}s, artifacts={args.num_artifacts}, "
        f"pitting={args.inject_pitting}, cl_peak={args.inject_cl_peak})"
    )

    sim = MQTTSensorSimulator(
        broker=args.broker,
        port=args.port,
        username=args.username,
        password=args.password,
        topic_prefix=args.topic_prefix,
        interval_seconds=interval,
        num_artifacts=args.num_artifacts,
        include_anomalies=not args.no_anomalies,
        inject_pitting=args.inject_pitting,
        inject_cl_peak=args.inject_cl_peak,
        peak_interval_hours=args.peak_interval,
        seed=args.seed,
    )

    try:
        asyncio.run(sim.run(duration_minutes=args.duration))
    except KeyboardInterrupt:
        logger.info("Exiting...")


if __name__ == "__main__":
    main()
