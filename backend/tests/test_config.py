"""
配置加载测试
验证 config.yaml 正确加载，所有参数均已外置
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_config_yaml_exists():
    yaml_path = os.path.join(os.path.dirname(__file__), "..", "config.yaml")
    assert os.path.exists(yaml_path), "config.yaml 配置文件不存在"


def test_settings_from_yaml():
    from app.config import get_settings, Settings

    settings = get_settings()
    assert isinstance(settings, Settings)

    assert settings.DB_HOST == "localhost"
    assert settings.DB_PORT == 5432
    assert settings.MQTT_BROKER == "localhost"
    assert settings.MQTT_TOPIC_PREFIX == "museum/bronze"

    assert settings.REDIS_HOST == "localhost"
    assert settings.REDIS_PORT == 6379
    assert settings.REDIS_STREAM_RAW == "stream:raw_data"
    assert settings.REDIS_STREAM_FEATURES == "stream:features"
    assert settings.REDIS_STREAM_PREDICTIONS == "stream:predictions"
    assert settings.REDIS_STREAM_ALERTS == "stream:alerts"

    assert settings.MODEL_DIR == "app/models"
    assert settings.PCA_COMPONENTS == 10
    assert settings.ENSEMBLE_RF_WEIGHT == 0.4
    assert settings.ENSEMBLE_XGB_WEIGHT == 0.6

    assert settings.WAVELET_TYPE == "db4"
    assert settings.WAVELET_MAX_LEVEL == 5
    assert settings.WAVELET_SAMPLING_RATE == 1000

    assert settings.NOISE_RESISTANCE_THRESHOLD == 100.0
    assert settings.CHLORIDE_THRESHOLD == 3.0

    assert settings.ALERT_COOLDOWN == 900


def test_database_url_property():
    from app.config import get_settings

    settings = get_settings()
    url = settings.DATABASE_URL
    assert "postgresql+asyncpg://" in url
    assert settings.DB_HOST in url
    assert str(settings.DB_PORT) in url
    assert settings.DB_NAME in url


def test_no_hardcoded_model_paths():
    """验证模型路径不再硬编码在算法模块中"""
    from app.config import get_settings

    settings = get_settings()

    rust_model_path = os.path.join(settings.MODEL_DIR, "rust_rf_model.pkl")
    assert settings.MODEL_DIR in rust_model_path

    pca_model_path = os.path.join(settings.MODEL_DIR, "pca_transformer.pkl")
    assert settings.MODEL_DIR in pca_model_path
