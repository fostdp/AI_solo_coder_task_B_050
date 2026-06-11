from sqlalchemy import (
    Column, String, Integer, BigInteger, SmallInteger, Float, Text,
    DateTime, Boolean, JSON, ForeignKey, Index, ARRAY, LargeBinary
)
from sqlalchemy.dialects.postgresql import DOUBLE_PRECISION, TIMESTAMP, JSONB
from ..database import Base
from datetime import datetime


class BronzeArtifact(Base):
    __tablename__ = "bronze_artifacts"

    artifact_id = Column(String(32), primary_key=True)
    name = Column(String(128), nullable=False)
    dynasty = Column(String(32), nullable=False)
    description = Column(Text)
    location = Column(String(64))
    showcase_id = Column(String(32))
    position_3d = Column(JSONB)
    model_path = Column(String(256))
    status = Column(SmallInteger, default=1)
    created_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow)
    updated_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow)


class Sensor(Base):
    __tablename__ = "sensors"

    sensor_id = Column(String(32), primary_key=True)
    sensor_type = Column(String(32), nullable=False)
    artifact_id = Column(String(32), ForeignKey("bronze_artifacts.artifact_id"))
    name = Column(String(128))
    install_position = Column(String(128))
    position_offset = Column(JSONB)
    status = Column(SmallInteger, default=1)
    calibration_data = Column(JSONB)
    created_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow)
    last_maintenance = Column(TIMESTAMP(timezone=True))


class ElectrochemicalNoiseData(Base):
    __tablename__ = "electrochemical_noise_data"

    time = Column(TIMESTAMP(timezone=True), primary_key=True)
    sensor_id = Column(String(32), ForeignKey("sensors.sensor_id"), primary_key=True)
    artifact_id = Column(String(32), ForeignKey("bronze_artifacts.artifact_id"))
    voltage_noise = Column(ARRAY(DOUBLE_PRECISION))
    current_noise = Column(ARRAY(DOUBLE_PRECISION))
    sampling_rate = Column(Integer)
    noise_resistance = Column(DOUBLE_PRECISION)
    pitting_index = Column(DOUBLE_PRECISION)
    std_voltage = Column(DOUBLE_PRECISION)
    std_current = Column(DOUBLE_PRECISION)
    skewness_voltage = Column(DOUBLE_PRECISION)
    kurtosis_voltage = Column(DOUBLE_PRECISION)
    raw_data = Column(LargeBinary)


class MicroenvironmentData(Base):
    __tablename__ = "microenvironment_data"

    time = Column(TIMESTAMP(timezone=True), primary_key=True)
    sensor_id = Column(String(32), ForeignKey("sensors.sensor_id"), primary_key=True)
    artifact_id = Column(String(32), ForeignKey("bronze_artifacts.artifact_id"))
    temperature = Column(DOUBLE_PRECISION)
    humidity = Column(DOUBLE_PRECISION)
    chloride_concentration = Column(DOUBLE_PRECISION)
    sulfur_dioxide = Column(DOUBLE_PRECISION)
    nitrogen_oxides = Column(DOUBLE_PRECISION)
    formaldehyde = Column(DOUBLE_PRECISION)
    voc_total = Column(DOUBLE_PRECISION)
    illuminance = Column(DOUBLE_PRECISION)
    uv_intensity = Column(DOUBLE_PRECISION)


class MicroscopeImage(Base):
    __tablename__ = "microscope_images"

    time = Column(TIMESTAMP(timezone=True), primary_key=True)
    sensor_id = Column(String(32), ForeignKey("sensors.sensor_id"), primary_key=True)
    artifact_id = Column(String(32), ForeignKey("bronze_artifacts.artifact_id"))
    image_path = Column(String(512))
    image_hash = Column(String(64))
    resolution = Column(String(32))
    magnification = Column(DOUBLE_PRECISION)
    rust_detection = Column(JSONB)
    surface_features = Column(JSONB)
    has_rust_eruption = Column(Boolean, default=False)
    confidence_score = Column(DOUBLE_PRECISION)


class RustPrediction(Base):
    __tablename__ = "rust_predictions"

    prediction_id = Column(BigInteger, primary_key=True, autoincrement=True)
    artifact_id = Column(String(32), ForeignKey("bronze_artifacts.artifact_id"))
    model_version = Column(String(32))
    prediction_time = Column(TIMESTAMP(timezone=True), nullable=False)
    target_window = Column(String(16))
    eruption_probability = Column(DOUBLE_PRECISION, nullable=False)
    risk_level = Column(SmallInteger, nullable=False)
    risk_zone = Column(JSONB)
    feature_contributions = Column(JSONB)
    model_input = Column(JSONB)
    created_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow)


class Alert(Base):
    __tablename__ = "alerts"

    alert_id = Column(BigInteger, primary_key=True, autoincrement=True)
    artifact_id = Column(String(32), ForeignKey("bronze_artifacts.artifact_id"))
    sensor_id = Column(String(32), ForeignKey("sensors.sensor_id"))
    alert_type = Column(String(32), nullable=False)
    severity = Column(SmallInteger, nullable=False)
    threshold_value = Column(DOUBLE_PRECISION)
    actual_value = Column(DOUBLE_PRECISION)
    message = Column(Text)
    alert_time = Column(TIMESTAMP(timezone=True), nullable=False)
    acknowledged = Column(Boolean, default=False)
    acknowledged_by = Column(String(64))
    acknowledged_at = Column(TIMESTAMP(timezone=True))
    resolved = Column(Boolean, default=False)
    resolved_at = Column(TIMESTAMP(timezone=True))
    wecom_sent = Column(Boolean, default=False)
    sms_sent = Column(Boolean, default=False)
    push_channels = Column(JSONB)
    created_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow)


class InhibitorSprayTask(Base):
    __tablename__ = "inhibitor_spray_tasks"

    task_id = Column(BigInteger, primary_key=True, autoincrement=True)
    artifact_id = Column(String(32), ForeignKey("bronze_artifacts.artifact_id"))
    alert_id = Column(BigInteger, ForeignKey("alerts.alert_id"))
    task_type = Column(String(32))
    inhibitor_type = Column(String(16), nullable=False)
    concentration = Column(DOUBLE_PRECISION)
    total_volume = Column(DOUBLE_PRECISION)
    target_zones = Column(JSONB)
    spray_plan = Column(JSONB)
    coverage_estimate = Column(DOUBLE_PRECISION)
    status = Column(SmallInteger, default=0)
    scheduled_at = Column(TIMESTAMP(timezone=True))
    started_at = Column(TIMESTAMP(timezone=True))
    completed_at = Column(TIMESTAMP(timezone=True))
    actual_volume = Column(DOUBLE_PRECISION)
    actual_coverage = Column(DOUBLE_PRECISION)
    operator = Column(String(64))
    notes = Column(Text)
    created_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow)


class SprayExecutionLog(Base):
    __tablename__ = "spray_execution_logs"

    time = Column(TIMESTAMP(timezone=True), primary_key=True)
    task_id = Column(BigInteger, ForeignKey("inhibitor_spray_tasks.task_id"), primary_key=True)
    nozzle_position = Column(JSONB)
    spray_pressure = Column(DOUBLE_PRECISION)
    flow_rate = Column(DOUBLE_PRECISION)
    current_zone = Column(String(32))
    droplet_size = Column(DOUBLE_PRECISION)
    coverage_progress = Column(DOUBLE_PRECISION)
