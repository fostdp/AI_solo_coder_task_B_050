from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import IntEnum


class RiskLevelEnum(IntEnum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    EXTREME = 4


class BronzeArtifactBase(BaseModel):
    artifact_id: str
    name: str
    dynasty: str
    description: Optional[str] = None
    location: Optional[str] = None
    showcase_id: Optional[str] = None
    position_3d: Optional[Dict[str, float]] = None
    status: Optional[int] = 1


class BronzeArtifactRead(BronzeArtifactBase):
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class SensorBase(BaseModel):
    sensor_id: str
    sensor_type: str
    artifact_id: Optional[str] = None
    name: Optional[str] = None
    install_position: Optional[str] = None
    status: Optional[int] = 1


class SensorRead(SensorBase):
    created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class ElectrochemicalNoiseDataIn(BaseModel):
    timestamp: Optional[str] = None
    sensor_id: str
    artifact_id: str
    voltage_noise: Optional[List[float]] = None
    current_noise: Optional[List[float]] = None
    sampling_rate: int = 1000
    noise_resistance: float
    pitting_index: Optional[float] = 0.0
    std_voltage: Optional[float] = None
    std_current: Optional[float] = None
    skewness_voltage: Optional[float] = None
    kurtosis_voltage: Optional[float] = None


class MicroenvironmentDataIn(BaseModel):
    timestamp: Optional[str] = None
    sensor_id: str
    artifact_id: str
    temperature: Optional[float] = None
    humidity: Optional[float] = None
    chloride_concentration: Optional[float] = None
    sulfur_dioxide: Optional[float] = None
    nitrogen_oxides: Optional[float] = None
    formaldehyde: Optional[float] = None
    voc_total: Optional[float] = None
    illuminance: Optional[float] = None
    uv_intensity: Optional[float] = None


class MicroscopeImageDataIn(BaseModel):
    timestamp: Optional[str] = None
    sensor_id: str
    artifact_id: str
    image_path: Optional[str] = None
    resolution: Optional[str] = None
    magnification: Optional[float] = 200.0
    rust_detection: Optional[Dict] = None
    surface_features: Optional[Dict] = None
    has_rust_eruption: bool = False
    confidence_score: Optional[float] = None


class AlertRead(BaseModel):
    alert_id: int
    artifact_id: Optional[str] = None
    sensor_id: Optional[str] = None
    alert_type: str
    severity: int
    threshold_value: Optional[float] = None
    actual_value: Optional[float] = None
    message: Optional[str] = None
    alert_time: datetime
    acknowledged: bool = False
    resolved: bool = False
    wecom_sent: bool = False
    sms_sent: bool = False
    push_channels: Optional[Dict] = None
    model_config = ConfigDict(from_attributes=True)


class AlertAcknowledge(BaseModel):
    operator: str
    notes: Optional[str] = None


class AlertResolve(BaseModel):
    notes: Optional[str] = None


class SprayTaskCreate(BaseModel):
    artifact_id: str
    alert_id: Optional[int] = None
    inhibitor_type: str = Field(default="BTA", pattern="^(BTA|AMT|MBO)$")
    target_zones: List[Dict]
    required_coverage: float = 0.95


class SprayTaskRead(BaseModel):
    task_id: int
    artifact_id: str
    alert_id: Optional[int] = None
    inhibitor_type: str
    total_volume: Optional[float] = None
    coverage_estimate: Optional[float] = None
    status: int
    target_zones: Optional[List[Dict]] = None
    spray_plan: Optional[Dict] = None
    scheduled_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class PredictionRead(BaseModel):
    prediction_id: int
    artifact_id: str
    prediction_time: datetime
    target_window: Optional[str] = None
    eruption_probability: float
    risk_level: int
    risk_zone: Optional[List[Dict]] = None
    feature_contributions: Optional[Dict] = None
    model_version: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class RealtimeStatus(BaseModel):
    artifact_id: str
    name: str
    dynasty: str
    status: int
    showcase_id: Optional[str] = None
    noise_resistance: Optional[float] = None
    ecn_update_time: Optional[datetime] = None
    temperature: Optional[float] = None
    humidity: Optional[float] = None
    chloride_concentration: Optional[float] = None
    sulfur_dioxide: Optional[float] = None
    menv_update_time: Optional[datetime] = None
    eruption_probability: Optional[float] = None
    risk_level: Optional[int] = None


class StatisticsResponse(BaseModel):
    total_artifacts: int = 0
    normal_count: int = 0
    warning_count: int = 0
    alert_count: int = 0
    eruption_count: int = 0
    active_alerts_24h: int = 0
    spray_tasks_pending: int = 0
    avg_noise_resistance: float = 0.0
    avg_chloride: float = 0.0
    sensors_online: int = 0
    sensors_total: int = 100
    predictions_today: int = 0


class TrendDataPoint(BaseModel):
    time: datetime
    value: float


class ApiResponse(BaseModel):
    success: bool = True
    message: str = "OK"
    data: Optional[Any] = None
    error: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
