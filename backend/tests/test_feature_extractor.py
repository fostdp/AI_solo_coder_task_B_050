"""
小波包特征提取 + PCA 降维 测试
验证 feature_extractor 微服务功能
"""
import os
import sys
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def sample_signals():
    np.random.seed(42)
    n = 512
    t = np.linspace(0, 0.5, n)
    freq = 50
    voltage = 0.01 * np.sin(2 * np.pi * freq * t) + np.random.normal(0, 0.002, n)
    current = 1e-6 * np.sin(2 * np.pi * freq * t) + np.random.normal(0, 2e-7, n)
    return voltage, current


def test_wavelet_feature_extractor_init():
    from app.algorithms.wavelet_features import WaveletPacketFeatureExtractor

    extractor = WaveletPacketFeatureExtractor(
        wavelet="db4", max_level=5, sampling_rate=1000
    )
    assert extractor.wavelet == "db4"
    assert extractor.max_level == 5
    assert extractor.sampling_rate == 1000


def test_wavelet_extract_shape(sample_signals):
    from app.algorithms.wavelet_features import WaveletPacketFeatureExtractor, features_to_feature_vector

    volt, curr = sample_signals
    extractor = WaveletPacketFeatureExtractor()
    features = extractor.extract(volt, curr)

    assert features.total_energy > 0
    assert len(features.band_energies) > 0
    assert len(features.band_energy_ratios) > 0
    assert features.wavelet_entropy > 0
    assert features.noise_resistance > 0
    assert features.pitting_index >= 0
    assert len(features.statistical_features) > 10

    vec, names = features_to_feature_vector(features)
    assert len(vec) == len(names)
    assert len(vec) >= 20


def test_statistical_features_present(sample_signals):
    from app.algorithms.wavelet_features import WaveletPacketFeatureExtractor

    volt, curr = sample_signals
    extractor = WaveletPacketFeatureExtractor()
    features = extractor.extract(volt, curr)

    stats = features.statistical_features
    expected_keys = [
        "V_mean", "V_std", "V_rms", "V_skew", "V_kurtosis",
        "V_peak_to_peak", "V_cv",
        "I_mean", "I_std", "I_rms", "I_skew", "I_kurtosis",
        "I_peak_to_peak", "I_cv", "cross_corr"
    ]
    for key in expected_keys:
        assert key in stats, f"缺少统计特征: {key}"
        assert isinstance(stats[key], float)


def test_band_energy_ratios_sum(sample_signals):
    from app.algorithms.wavelet_features import WaveletPacketFeatureExtractor

    volt, curr = sample_signals
    extractor = WaveletPacketFeatureExtractor()
    features = extractor.extract(volt, curr)

    v_ratios = [v for k, v in features.band_energy_ratios.items() if k.startswith("V_") and k.endswith("_ratio")]
    i_ratios = [v for k, v in features.band_energy_ratios.items() if k.startswith("I_") and k.endswith("_ratio")]

    assert len(v_ratios) == 32, f"应有32个电压子带, 实际 {len(v_ratios)}"
    assert len(i_ratios) == 32, f"应有32个电流子带, 实际 {len(i_ratios)}"

    assert abs(sum(v_ratios) - 1.0) < 0.01, f"电压能量比之和应≈1, 实际 {sum(v_ratios)}"
    assert abs(sum(i_ratios) - 1.0) < 0.01, f"电流能量比之和应≈1, 实际 {sum(i_ratios)}"


def test_pca_transformer():
    from app.algorithms.pca_transformer import PCATransformer
    from app.config import get_settings

    settings = get_settings()
    np.random.seed(42)

    n_samples = 100
    n_features = 72
    X = np.random.randn(n_samples, n_features)

    pca = PCATransformer(n_components=settings.PCA_COMPONENTS, model_dir=settings.MODEL_DIR)
    X_pca = pca.fit_transform(X)

    assert X_pca.shape == (n_samples, settings.PCA_COMPONENTS)
    assert pca._fitted == True
    assert pca.get_explained_variance() > 0

    X_new = np.random.randn(10, n_features)
    X_new_pca = pca.transform(X_new)
    assert X_new_pca.shape == (10, settings.PCA_COMPONENTS)


def test_feature_extractor_service_sync():
    from app.services.feature_extractor import FeatureExtractorService

    np.random.seed(42)
    n = 512
    volt = np.random.normal(0, 0.01, n)
    curr = np.random.normal(0, 1e-6, n)

    service = FeatureExtractorService(stream_manager=None)
    service._init_components()

    result = service.extract_sync(volt, curr, artifact_id="test_001")

    assert result is not None
    assert result.artifact_id == "test_001"
    assert len(result.pca_features) > 0
    assert result.pca_dimensions > 0
    assert result.raw_feature_count > 0
    assert result.noise_resistance > 0
    assert len(result.statistical_features) > 10
    assert len(result.band_energy_ratios) > 0


def test_short_signal_handling():
    from app.algorithms.wavelet_features import WaveletPacketFeatureExtractor

    extractor = WaveletPacketFeatureExtractor()

    short_volt = np.array([0.1, 0.2, 0.3])
    short_curr = np.array([0.01, 0.02, 0.03])

    features = extractor.extract(short_volt, short_curr)
    assert features is not None
    assert features.total_energy >= 0


def test_noise_resistance_calculation(sample_signals):
    from app.algorithms.wavelet_features import WaveletPacketFeatureExtractor

    volt, curr = sample_signals
    extractor = WaveletPacketFeatureExtractor()
    features = extractor.extract(volt, curr)

    Rn = features.noise_resistance
    assert Rn > 0
    assert Rn < 1e10
