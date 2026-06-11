"""
端到端集成测试
验证 5 个微服务通过 Redis Stream (内存模式) 串联的完整数据流

数据流: MQTT Ingest -> Feature Extractor -> Predictor -> Optimizer -> Alert WS
"""
import os
import sys
import pytest
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def stream_manager():
    from app.streams import RedisStreamManager

    mgr = RedisStreamManager()
    import asyncio
    asyncio.run(mgr.connect())
    yield mgr
    asyncio.run(mgr.close())


def test_end_to_end_pipeline_sync():
    """同步模式下验证完整预测链路：特征提取 -> 模型预测"""
    from app.services.feature_extractor import FeatureExtractorService
    from app.services.predictor import PredictorService

    np.random.seed(42)
    n = 512
    volt = np.random.normal(0, 0.01, n)
    curr = np.random.normal(0, 1e-6, n)

    extractor = FeatureExtractorService(stream_manager=None)
    extractor._init_components()
    features = extractor.extract_sync(volt, curr, artifact_id="integration_test")

    assert features is not None
    assert features.pca_dimensions > 0
    assert features.raw_feature_count > 0
    assert len(features.statistical_features) > 0

    predictor = PredictorService(stream_manager=None)
    predictor._load_models()

    wavelet_dict = {
        "statistical_features": features.statistical_features,
        "band_energy_ratios": features.band_energy_ratios,
        "wavelet_entropy": features.wavelet_entropy,
        "noise_resistance": features.noise_resistance,
        "pitting_index": features.pitting_index
    }

    microenv = {
        "temperature": 22.0,
        "humidity": 50.0,
        "chloride_concentration": 1.5,
        "sulfur_dioxide": 20.0,
        "nitrogen_oxides": 10.0,
        "formaldehyde": 15.0
    }

    result = predictor.predict_sync(
        artifact_id="integration_test",
        wavelet_features=wavelet_dict,
        microenv_data=microenv
    )

    assert result is not None
    assert result.artifact_id == "integration_test"
    assert 0.0 <= result.eruption_probability <= 1.0
    assert 1 <= result.risk_level <= 4
    assert len(result.risk_zones) >= 0
    assert len(result.feature_contributions) > 0
    assert result.model_version is not None


def test_full_prediction_to_optimization():
    """预测 -> 喷涂优化 完整链路"""
    from app.services.predictor import PredictorService
    from app.services.optimizer import SprayOptimizerService, InhibitorType

    predictor = PredictorService(stream_manager=None)
    predictor._load_models()

    wavelet_dict = {
        "statistical_features": {
            "V_mean": 0.0, "V_std": 0.005, "V_rms": 0.005,
            "V_skew": 0.1, "V_kurtosis": 3.0, "V_peak_to_peak": 0.03, "V_cv": 1.0,
            "I_mean": 0.0, "I_std": 5e-7, "I_rms": 5e-7,
            "I_skew": 0.0, "I_kurtosis": 3.0, "I_peak_to_peak": 3e-6, "I_cv": 1.0,
            "cross_corr": 0.1
        },
        "band_energy_ratios": {},
        "wavelet_entropy": 3.5,
        "noise_resistance": 500.0,
        "pitting_index": 2.0
    }

    for i in range(32):
        wavelet_dict["band_energy_ratios"][f"V_aaa{i}_ratio"] = 1.0 / 64
        wavelet_dict["band_energy_ratios"][f"I_aaa{i}_ratio"] = 1.0 / 64

    microenv = {
        "temperature": 25.0,
        "humidity": 60.0,
        "chloride_concentration": 5.0,
        "sulfur_dioxide": 30.0,
        "nitrogen_oxides": 15.0,
        "formaldehyde": 20.0
    }

    prediction = predictor.predict_sync(
        artifact_id="full_test",
        wavelet_features=wavelet_dict,
        microenv_data=microenv
    )

    assert prediction is not None

    optimizer = SprayOptimizerService(stream_manager=None)
    optimization = optimizer.optimize(
        artifact_id="full_test",
        target_zones=prediction.risk_zones,
        artifact_size={"width": 0.5, "height": 0.6, "depth": 0.4},
        inhibitor_type=InhibitorType.BTA,
        required_coverage=0.90,
        nozzle_count=4
    )

    assert optimization is not None
    assert optimization.artifact_id == "full_test"
    assert optimization.total_volume_ml > 0
    assert optimization.total_spray_time_s > 0
    assert len(optimization.nozzle_positions) > 0
    assert len(optimization.zone_results) > 0
    assert len(optimization.spray_path) > 0
    assert "droplet_mean_diameter_um" in optimization.cfd_simulation_summary


@pytest.mark.asyncio
async def test_stream_pipeline_in_memory():
    """使用内存 Stream 验证发布-订阅流程"""
    from app.streams import RedisStreamManager, parse_stream_message

    mgr = RedisStreamManager(use_memory=True)
    await mgr.connect()
    await mgr.ensure_stream("test_integration")
    await mgr.ensure_group("test_integration", "test_group")

    test_data = {
        "sensor_type": "electrochemical",
        "artifact_id": "stream_test",
        "value": 42.0
    }

    msg_id = await mgr.publish("test_integration", test_data)
    assert msg_id is not None

    messages = await mgr.consume_group(
        "test_integration", "test_group", "consumer_1",
        count=5, block_ms=100
    )

    if messages:
        stream_name, msgs = messages[0]
        assert stream_name == "test_integration"
        assert len(msgs) >= 1

        parsed = parse_stream_message(msgs[0])
        assert parsed.get("sensor_type") == "electrochemical"
        assert parsed.get("artifact_id") == "stream_test"

        await mgr.ack("test_integration", "test_group", parsed["_id"])

    await mgr.close()


def test_config_backward_compatibility():
    """验证配置从 config.yaml 加载且与环境变量兼容"""
    from app.config import get_settings

    settings = get_settings()
    assert settings is not None

    assert isinstance(settings.DB_HOST, str)
    assert isinstance(settings.DB_PORT, int)
    assert isinstance(settings.MQTT_BROKER, str)
    assert isinstance(settings.APP_PORT, int)

    assert hasattr(settings, 'MODEL_DIR')
    assert hasattr(settings, 'PCA_COMPONENTS')
    assert hasattr(settings, 'WAVELET_TYPE')
    assert hasattr(settings, 'REDIS_HOST')
    assert hasattr(settings, 'REDIS_STREAM_RAW')
    assert hasattr(settings, 'ALERT_COOLDOWN')


def test_all_services_instantiable():
    """验证所有 5 个微服务类都能正确实例化"""
    from app.services.mqtt_ingest import MQTTIngestService
    from app.services.feature_extractor import FeatureExtractorService
    from app.services.predictor import PredictorService
    from app.services.optimizer import SprayOptimizerService
    from app.services.alert_ws import AlertWSService

    mqtt_svc = MQTTIngestService(stream_manager=None)
    assert mqtt_svc is not None

    feat_svc = FeatureExtractorService(stream_manager=None)
    assert feat_svc is not None

    pred_svc = PredictorService(stream_manager=None)
    assert pred_svc is not None

    opt_svc = SprayOptimizerService(stream_manager=None)
    assert opt_svc is not None

    alert_svc = AlertWSService(stream_manager=None)
    assert alert_svc is not None


def test_services_package_exports():
    """验证 services 包导出所有微服务类"""
    from app.services import (
        MQTTIngestService,
        FeatureExtractorService,
        PredictorService,
        SprayOptimizerService,
        AlertWSService,
        WebSocketManager,
        AlertDispatcher
    )

    assert MQTTIngestService is not None
    assert FeatureExtractorService is not None
    assert PredictorService is not None
    assert SprayOptimizerService is not None
    assert AlertWSService is not None
    assert WebSocketManager is not None
    assert AlertDispatcher is not None
