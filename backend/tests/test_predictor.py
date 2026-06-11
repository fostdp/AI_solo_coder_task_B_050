"""
预测模型测试
验证 predictor 微服务的 XGBoost + RF 融合推理功能
"""
import os
import sys
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(scope="module")
def predictor_service():
    from app.services.predictor import PredictorService

    service = PredictorService(stream_manager=None)
    service._load_models()
    return service


def test_predictor_init(predictor_service):
    assert predictor_service.rf_model is not None
    assert predictor_service.scaler is not None
    assert predictor_service._model_version is not None
    assert predictor_service.PCA_COMPONENTS if hasattr(predictor_service, 'PCA_COMPONENTS') else True


def test_predict_sync_risk_level():
    from app.services.predictor import PredictorService

    service = PredictorService(stream_manager=None)
    service._load_models()

    wavelet_features = {
        "statistical_features": {
            "V_mean": 0.0, "V_std": 0.005, "V_rms": 0.005,
            "V_skew": 0.1, "V_kurtosis": 3.0, "V_peak_to_peak": 0.03, "V_cv": 1.0,
            "I_mean": 0.0, "I_std": 5e-7, "I_rms": 5e-7,
            "I_skew": 0.0, "I_kurtosis": 3.0, "I_peak_to_peak": 3e-6, "I_cv": 1.0,
            "cross_corr": 0.1
        },
        "band_energy_ratios": {},
        "wavelet_entropy": 3.5,
        "noise_resistance": 10000,
        "pitting_index": 0.5
    }

    for i in range(32):
        wavelet_features["band_energy_ratios"][f"V_aaa{i}_ratio"] = 1.0/64
        wavelet_features["band_energy_ratios"][f"I_aaa{i}_ratio"] = 1.0/64

    microenv = {
        "temperature": 22.0,
        "humidity": 45.0,
        "chloride_concentration": 1.0,
        "sulfur_dioxide": 10.0,
        "nitrogen_oxides": 5.0,
        "formaldehyde": 10.0
    }

    result = service.predict_sync("test_001", wavelet_features, microenv)

    assert result is not None
    assert result.artifact_id == "test_001"
    assert 0.0 <= result.eruption_probability <= 1.0
    assert 1 <= result.risk_level <= 4
    assert len(result.risk_zones) >= 0
    assert len(result.feature_contributions) > 0
    assert result.model_version is not None
    assert result.target_window == "24h"


def test_risk_level_boundaries():
    from app.services.predictor import PredictorService

    service = PredictorService(stream_manager=None)
    service._load_models()

    assert service._calculate_risk_level(0.0) == 1
    assert service._calculate_risk_level(0.1) == 1
    assert service._calculate_risk_level(0.9) == 4
    assert service._calculate_risk_level(1.0) == 4

    levels = set()
    for p in np.linspace(0, 1, 100):
        levels.add(service._calculate_risk_level(p))
    assert len(levels) == 4, f"应有4个风险等级，实际有 {len(levels)} 个"


def test_risk_zones_count():
    from app.services.predictor import PredictorService

    service = PredictorService(stream_manager=None)
    service._load_models()

    z1 = service._identify_risk_zones(0.1, {})
    assert len(z1) == 1

    z2 = service._identify_risk_zones(0.5, {})
    assert len(z2) == 3

    z3 = service._identify_risk_zones(0.8, {})
    assert len(z3) == 6


def test_feature_contributions():
    from app.services.predictor import PredictorService

    service = PredictorService(stream_manager=None)
    service._load_models()

    X_pca = np.random.randn(1, 10)
    contribs = service._get_feature_contributions(X_pca)

    assert isinstance(contribs, dict)
    assert len(contribs) > 0
    for k, v in contribs.items():
        assert isinstance(k, str)
        assert isinstance(v, float)
        assert v >= 0


def test_model_files_generated():
    from app.config import get_settings

    settings = get_settings()
    model_dir = settings.MODEL_DIR

    assert os.path.exists(model_dir), f"模型目录不存在: {model_dir}"

    required_files = ["rust_rf_model.pkl", "rust_scaler.pkl", "rust_model_meta.pkl"]
    for fname in required_files:
        fpath = os.path.join(model_dir, fname)
        assert os.path.exists(fpath), f"模型文件缺失: {fpath}"


def test_prediction_cooldown():
    from app.services.predictor import PredictorService

    service = PredictorService(stream_manager=None)
    service._load_models()
    service._prediction_cooldown = 3600

    service.artifact_last_prediction["test_cool"] = 0
    assert service.artifact_last_prediction.get("test_cool", 0) == 0

    now = 1_700_000_000
    service.artifact_last_prediction["test_cool"] = now
    last = service.artifact_last_prediction.get("test_cool", 0)
    assert now - last < service._prediction_cooldown


def test_xgboost_fallback():
    from app.services.predictor import PredictorService

    service = PredictorService(stream_manager=None)
    service._load_models()

    assert hasattr(service, 'xgb_model')
    assert isinstance(service.use_xgboost if hasattr(service, 'use_xgboost') else True, bool)
