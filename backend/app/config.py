from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Dict, Optional, Any
import os
import yaml


def _load_yaml_config() -> Dict[str, Any]:
    yaml_path = os.path.join(os.path.dirname(__file__), "..", "config.yaml")
    if os.path.exists(yaml_path):
        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            pass
    return {}


_yaml_cfg = _load_yaml_config()


def _from_yaml(*keys, default=None):
    val = _yaml_cfg
    for k in keys:
        if isinstance(val, dict) and k in val:
            val = val[k]
        else:
            return default
    return val if val is not None else default


class Settings(BaseSettings):
    DB_HOST: str = _from_yaml("database", "host", default="localhost")
    DB_PORT: int = _from_yaml("database", "port", default=5432)
    DB_USER: str = _from_yaml("database", "user", default="postgres")
    DB_PASSWORD: str = _from_yaml("database", "password", default="postgres")
    DB_NAME: str = _from_yaml("database", "name", default="bronze_monitor")

    MQTT_BROKER: str = _from_yaml("mqtt", "broker", default="localhost")
    MQTT_PORT: int = _from_yaml("mqtt", "port", default=1883)
    MQTT_USERNAME: str = _from_yaml("mqtt", "username", default="admin")
    MQTT_PASSWORD: str = _from_yaml("mqtt", "password", default="admin")
    MQTT_TOPIC_PREFIX: str = _from_yaml("mqtt", "topic_prefix", default="museum/bronze")

    REDIS_HOST: str = _from_yaml("redis", "host", default="localhost")
    REDIS_PORT: int = _from_yaml("redis", "port", default=6379)
    REDIS_DB: int = _from_yaml("redis", "db", default=0)
    REDIS_STREAM_RAW: str = _from_yaml("redis", "streams", "raw_data", default="stream:raw_data")
    REDIS_STREAM_FEATURES: str = _from_yaml("redis", "streams", "features", default="stream:features")
    REDIS_STREAM_PREDICTIONS: str = _from_yaml("redis", "streams", "predictions", default="stream:predictions")
    REDIS_STREAM_ALERTS: str = _from_yaml("redis", "streams", "alerts", default="stream:alerts")
    REDIS_GROUP_FEATURE: str = _from_yaml("redis", "groups", "feature_extractor", default="group:feature_extractor")
    REDIS_GROUP_PREDICTOR: str = _from_yaml("redis", "groups", "predictor", default="group:predictor")
    REDIS_GROUP_ALERT: str = _from_yaml("redis", "groups", "alert_ws", default="group:alert_ws")

    APP_HOST: str = _from_yaml("app", "host", default="0.0.0.0")
    APP_PORT: int = _from_yaml("app", "port", default=8000)
    APP_ENV: str = _from_yaml("app", "env", default="development")

    WECOM_WEBHOOK_URL: str = _from_yaml("alerts", "wecom_webhook_url", default="")
    SMS_API_URL: str = _from_yaml("alerts", "sms_api_url", default="")
    SMS_API_KEY: str = _from_yaml("alerts", "sms_api_key", default="")
    SMS_SENDER: str = _from_yaml("alerts", "sms_sender", default="")
    ALERT_COOLDOWN: int = _from_yaml("alerts", "cooldown_seconds", default=900)

    NOISE_RESISTANCE_THRESHOLD: float = _from_yaml("thresholds", "noise_resistance", default=100.0)
    CHLORIDE_THRESHOLD: float = _from_yaml("thresholds", "chloride", default=3.0)
    SULFUR_DIOXIDE_THRESHOLD: float = _from_yaml("thresholds", "sulfur_dioxide", default=50.0)
    TEMPERATURE_HIGH_THRESHOLD: float = _from_yaml("thresholds", "temperature_high", default=30.0)
    HUMIDITY_HIGH_THRESHOLD: float = _from_yaml("thresholds", "humidity_high", default=70.0)

    MODEL_DIR: str = _from_yaml("models", "dir", default="app/models")
    PCA_COMPONENTS: int = _from_yaml("models", "pca_components", default=10)
    ENSEMBLE_RF_WEIGHT: float = _from_yaml("models", "rf_weight", default=0.4)
    ENSEMBLE_XGB_WEIGHT: float = _from_yaml("models", "xgb_weight", default=0.6)

    WAVELET_TYPE: str = _from_yaml("models", "wavelet", "wavelet_type", default="db4")
    WAVELET_MAX_LEVEL: int = _from_yaml("models", "wavelet", "max_level", default=5)
    WAVELET_SAMPLING_RATE: int = _from_yaml("models", "wavelet", "sampling_rate", default=1000)

    REPORT_INTERVAL: int = _from_yaml("app", "report_interval", default=900)

    class Config:
        env_file = ".env"
        case_sensitive = True

    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    @property
    def DATABASE_URL_SYNC(self) -> str:
        return f"postgresql+psycopg2://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
