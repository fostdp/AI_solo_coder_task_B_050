"""
拉曼光谱识别模块测试
覆盖：正常/边界/异常场景
"""
import os
import sys
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.algorithms.raman_cnn import (
    Raman1DCNNClassifier,
    RamanSpectrum,
    RustProductType,
    STANDARD_RAMAN_PEAKS,
    get_raman_color,
    get_product_chinese_name,
)


def _make_pure_spectrum(product_type: RustProductType, snr_db: float = 40.0) -> RamanSpectrum:
    """生成纯锈蚀产物模拟拉曼光谱"""
    rng = np.random.RandomState(hash(product_type.value) % 2**31)
    target_wn = np.linspace(100, 3500, 2048)
    peaks = STANDARD_RAMAN_PEAKS.get(product_type, [])
    intensities = np.zeros_like(target_wn)
    for p in peaks:
        amp = rng.uniform(0.8, 1.2)
        width = rng.uniform(10, 20)
        intensities += amp * np.exp(-0.5 * ((target_wn - p) / width) ** 2)

    signal_power = np.mean(intensities ** 2)
    noise_power = signal_power / (10 ** (snr_db / 10)) if snr_db > 0 else signal_power * 10
    noise_std = np.sqrt(noise_power)
    intensities += rng.normal(0, noise_std, len(intensities))
    intensities = np.clip(intensities, 0, None)

    return RamanSpectrum.from_lists(target_wn.tolist(), intensities.tolist())


def _make_partial_spectrum(product_type: RustProductType, wn_range=(500, 2000)) -> RamanSpectrum:
    """生成波数范围缺失的光谱"""
    rng = np.random.RandomState(99)
    target_wn = np.linspace(wn_range[0], wn_range[1], 1024)
    peaks = STANDARD_RAMAN_PEAKS.get(product_type, [])
    intensities = np.zeros_like(target_wn)
    for p in peaks:
        if wn_range[0] <= p <= wn_range[1]:
            intensities += np.exp(-0.5 * ((target_wn - p) / 15) ** 2)
    intensities += rng.normal(0, 0.03, len(intensities))
    intensities = np.clip(intensities, 0, None)
    return RamanSpectrum.from_lists(target_wn.tolist(), intensities.tolist())


# ============================================================
# 正常场景
# ============================================================

class TestRamanNormal:
    """正常场景测试"""

    def test_pure_atacamite_high_confidence(self):
        """模拟纯氯铜矿光谱，输出概率>0.7（与孔雀石峰位重叠多，置信度略低）"""
        clf = Raman1DCNNClassifier(model_dir="app/models_test_empty")
        spec = _make_pure_spectrum(RustProductType.ATACAMITE, snr_db=40)
        result = clf.predict(spec, artifact_id="TEST001")
        assert result.product_type == RustProductType.ATACAMITE
        assert result.confidence > 0.7
        assert result.probabilities["atacamite"] > 0.7

    def test_pure_malachite_recognized(self):
        """模拟纯孔雀石光谱，正确识别"""
        clf = Raman1DCNNClassifier(model_dir="app/models_test_empty")
        spec = _make_pure_spectrum(RustProductType.MALACHITE, snr_db=40)
        result = clf.predict(spec, artifact_id="TEST002")
        assert result.product_type == RustProductType.MALACHITE
        assert result.confidence > 0.5

    def test_pure_cassiterite_recognized(self):
        """模拟纯锡石光谱，正确识别"""
        clf = Raman1DCNNClassifier(model_dir="app/models_test_empty")
        spec = _make_pure_spectrum(RustProductType.CASSITERITE, snr_db=40)
        result = clf.predict(spec, artifact_id="TEST003")
        assert result.product_type == RustProductType.CASSITERITE
        assert result.confidence > 0.8

    def test_pure_cuprite_recognized(self):
        """模拟纯赤铜矿光谱，正确识别"""
        clf = Raman1DCNNClassifier(model_dir="app/models_test_empty")
        spec = _make_pure_spectrum(RustProductType.CUPRITE, snr_db=40)
        result = clf.predict(spec, artifact_id="TEST004")
        assert result.product_type == RustProductType.CUPRITE
        assert result.confidence > 0.7

    def test_pure_azurite_recognized(self):
        """模拟纯蓝铜矿光谱，正确识别"""
        clf = Raman1DCNNClassifier(model_dir="app/models_test_empty")
        spec = _make_pure_spectrum(RustProductType.AZURITE, snr_db=40)
        result = clf.predict(spec, artifact_id="TEST005")
        assert result.product_type == RustProductType.AZURITE
        assert result.confidence > 0.7

    def test_prediction_has_all_fields(self):
        """预测结果包含所有必需字段"""
        clf = Raman1DCNNClassifier(model_dir="app/models_test_empty")
        spec = _make_pure_spectrum(RustProductType.ATACAMITE)
        result = clf.predict(spec, artifact_id="TEST006", sensor_id="RAM001",
                             position={"x": 0.1, "y": 0.2, "z": 0.3})
        assert result.artifact_id == "TEST006"
        assert result.sensor_id == "RAM001"
        assert result.position == {"x": 0.1, "y": 0.2, "z": 0.3}
        assert result.prediction_time != ""
        assert isinstance(result.peak_positions, list)
        assert isinstance(result.probabilities, dict)
        assert len(result.probabilities) >= 5

    def test_probabilities_sum_near_one(self):
        """概率之和接近1"""
        clf = Raman1DCNNClassifier(model_dir="app/models_test_empty")
        spec = _make_pure_spectrum(RustProductType.MALACHITE)
        result = clf.predict(spec, artifact_id="TEST007")
        total = sum(result.probabilities.values())
        assert abs(total - 1.0) < 0.15

    def test_color_mapping_complete(self):
        """每种锈蚀产物都有对应颜色"""
        for pt in RustProductType:
            color = get_raman_color(pt)
            assert color.startswith("#")
            assert len(color) == 7

    def test_chinese_name_complete(self):
        """每种锈蚀产物都有中文名称"""
        for pt in RustProductType:
            name = get_product_chinese_name(pt)
            assert len(name) > 0


# ============================================================
# 边界场景
# ============================================================

class TestRamanBoundary:
    """边界场景测试"""

    def test_low_snr_output_uncertain(self):
        """信噪比<5dB时，匹配的recall下降，概率分布趋于均匀"""
        clf = Raman1DCNNClassifier(model_dir="app/models_test_empty")
        spec = _make_pure_spectrum(RustProductType.ATACAMITE, snr_db=3)
        result = clf.predict(spec, artifact_id="TEST_B01")
        assert result is not None
        top2 = sorted(result.probabilities.values(), reverse=True)
        gap = top2[0] - top2[1]
        assert gap < 0.75

    def test_very_short_spectrum(self):
        """极短光谱（<10个点）仍能处理"""
        clf = Raman1DCNNClassifier(model_dir="app/models_test_empty")
        wn = [200, 400, 600, 800, 1000]
        inten = [0.5, 0.8, 1.0, 0.7, 0.3]
        spec = RamanSpectrum.from_lists(wn, inten)
        result = clf.predict(spec, artifact_id="TEST_B02")
        assert result is not None
        assert result.confidence >= 0.0

    def test_empty_intensities(self):
        """全零强度光谱"""
        clf = Raman1DCNNClassifier(model_dir="app/models_test_empty")
        wn = np.linspace(100, 3500, 512).tolist()
        inten = np.zeros(512).tolist()
        spec = RamanSpectrum.from_lists(wn, inten)
        result = clf.predict(spec, artifact_id="TEST_B03")
        assert result is not None

    def test_negative_intensities(self):
        """含负值的光谱（基线未校正）"""
        clf = Raman1DCNNClassifier(model_dir="app/models_test_empty")
        spec = _make_pure_spectrum(RustProductType.MALACHITE, snr_db=20)
        shifted = spec.intensities - 0.5
        spec_neg = RamanSpectrum(spec.wavenumbers, shifted)
        result = clf.predict(spec_neg, artifact_id="TEST_B04")
        assert result is not None

    def test_single_peak_spectrum(self):
        """仅含单个特征峰的光谱"""
        clf = Raman1DCNNClassifier(model_dir="app/models_test_empty")
        wn = np.linspace(100, 3500, 1024)
        inten = np.exp(-0.5 * ((wn - 432) / 12) ** 2) + 0.01
        spec = RamanSpectrum.from_lists(wn.tolist(), inten.tolist())
        result = clf.predict(spec, artifact_id="TEST_B05")
        assert result is not None

    def test_peak_detection_finds_known_peaks(self):
        """特征峰检测能找到已知峰位"""
        clf = Raman1DCNNClassifier(model_dir="app/models_test_empty")
        spec = _make_pure_spectrum(RustProductType.ATACAMITE, snr_db=30)
        peaks = clf.detect_peaks(spec)
        assert len(peaks) > 0
        std_peaks = STANDARD_RAMAN_PEAKS[RustProductType.ATACAMITE]
        matched = sum(1 for sp in std_peaks if any(abs(p - sp) < 15 for p in peaks))
        assert matched >= 3


# ============================================================
# 异常场景
# ============================================================

class TestRamanAbnormal:
    """异常场景测试"""

    def test_missing_wavenumber_range(self):
        """波数范围缺失(仅500-2000cm⁻¹)，插值后仍可识别"""
        clf = Raman1DCNNClassifier(model_dir="app/models_test_empty")
        spec = _make_partial_spectrum(RustProductType.ATACAMITE, wn_range=(500, 2000))
        result = clf.predict(spec, artifact_id="TEST_E01")
        assert result is not None
        assert isinstance(result.product_type, RustProductType)

    def test_nonstandard_wavenumber_spacing(self):
        """非均匀波数间隔（对数间距）"""
        clf = Raman1DCNNClassifier(model_dir="app/models_test_empty")
        wn = np.logspace(np.log10(100), np.log10(3500), 800)
        rng = np.random.RandomState(42)
        inten = rng.uniform(0, 0.5, 800)
        for p in STANDARD_RAMAN_PEAKS[RustProductType.MALACHITE][:5]:
            idx = np.argmin(np.abs(wn - p))
            inten[max(0, idx - 5):idx + 5] += 0.8
        spec = RamanSpectrum.from_lists(wn.tolist(), inten.tolist())
        result = clf.predict(spec, artifact_id="TEST_E02")
        assert result is not None

    def test_extremely_high_intensities(self):
        """极端高强度值（>1e6）"""
        clf = Raman1DCNNClassifier(model_dir="app/models_test_empty")
        spec = _make_pure_spectrum(RustProductType.CUPRITE)
        scaled = RamanSpectrum(spec.wavenumbers, spec.intensities * 1e6)
        result = clf.predict(scaled, artifact_id="TEST_E03")
        assert result is not None
        assert 0.0 <= result.confidence <= 1.0

    def test_reversed_wavenumber_order(self):
        """波数逆序（从高到低）"""
        clf = Raman1DCNNClassifier(model_dir="app/models_test_empty")
        spec = _make_pure_spectrum(RustProductType.AZURITE)
        rev_wn = spec.wavenumbers[::-1]
        rev_inten = spec.intensities[::-1]
        rev_spec = RamanSpectrum(rev_wn, rev_inten)
        result = clf.predict(rev_spec, artifact_id="TEST_E04")
        assert result is not None

    def test_nan_in_intensities(self):
        """强度中含NaN值"""
        clf = Raman1DCNNClassifier(model_dir="app/models_test_empty")
        spec = _make_pure_spectrum(RustProductType.MALACHITE)
        inten_with_nan = spec.intensities.copy()
        inten_with_nan[100:110] = np.nan
        nan_spec = RamanSpectrum(spec.wavenumbers, inten_with_nan)
        processed = clf.preprocess_spectrum(nan_spec)
        assert not np.any(np.isnan(processed))

    def test_preprocess_normalizes_to_0_1(self):
        """预处理结果归一化到[0,1]"""
        clf = Raman1DCNNClassifier(model_dir="app/models_test_empty")
        spec = _make_pure_spectrum(RustProductType.ATACAMITE)
        processed = clf.preprocess_spectrum(spec)
        assert processed.max() <= 1.0 + 1e-6
        assert processed.min() >= -1e-6
        assert len(processed) == clf.SPECTRUM_LENGTH
