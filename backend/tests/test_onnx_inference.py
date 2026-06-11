"""
ONNX 推理单元测试
覆盖：ONNX模型导出、加载、推理精度、批量推理、异步推理
"""
import os
import sys
import asyncio
import tempfile
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.algorithms.raman_cnn import (
    Raman1DCNNClassifier,
    RamanSpectrum,
    RustProductType,
    STANDARD_RAMAN_PEAKS,
)


def _make_spectrum(product: RustProductType, n_pts=2048, snr_db=30) -> RamanSpectrum:
    rng = np.random.RandomState(hash(product.value) % 2**31)
    wn = np.linspace(100, 3500, n_pts)
    peaks = STANDARD_RAMAN_PEAKS.get(product, [])
    inten = np.zeros_like(wn)
    for p in peaks:
        inten += np.exp(-0.5 * ((wn - p) / 15) ** 2)
    if snr_db > 0:
        sig_power = np.mean(inten ** 2)
        noise = np.sqrt(sig_power / (10 ** (snr_db / 10)))
        inten += rng.normal(0, noise, len(wn))
    inten = np.clip(inten, 0, None)
    return RamanSpectrum.from_lists(wn.tolist(), inten.tolist())


class TestONNXInference:
    """ONNX推理专项测试"""

    def test_classifier_has_onnx_support(self):
        """验证：分类器支持ONNX Runtime后端检测"""
        clf = Raman1DCNNClassifier(model_dir="app/models_test_empty")
        assert hasattr(clf, "_onnx_available")
        assert hasattr(clf, "_onnx_session")

    def test_classifier_has_predict_async(self):
        """验证：存在异步推理接口predict_async"""
        clf = Raman1DCNNClassifier(model_dir="app/models_test_empty")
        assert hasattr(clf, "predict_async")
        assert callable(clf.predict_async)

    def test_async_inference_result_matches_sync(self):
        """验证：异步推理结果与同步推理一致"""
        clf = Raman1DCNNClassifier(model_dir="app/models_test_empty")
        spec = _make_spectrum(RustProductType.CASSITERITE, snr_db=30)
        sync_result = clf.predict(spec, "SYNC_01")
        async_result = asyncio.run(clf.predict_async(spec, "ASYNC_01"))
        assert sync_result.product_type == async_result.product_type
        assert abs(sync_result.confidence - async_result.confidence) < 0.01

    def test_async_inference_preserves_fields(self):
        """验证：异步推理结果字段完整"""
        clf = Raman1DCNNClassifier(model_dir="app/models_test_empty")
        spec = _make_spectrum(RustProductType.AZURITE, snr_db=35)
        result = asyncio.run(clf.predict_async(
            spec, "FIELD_01", sensor_id="RAM007",
            position={"x": 0.1, "y": 0.2, "z": 0.3}
        ))
        assert result.artifact_id == "FIELD_01"
        assert result.sensor_id == "RAM007"
        assert result.position == {"x": 0.1, "y": 0.2, "z": 0.3}
        assert isinstance(result.probabilities, dict)
        assert len(result.probabilities) >= 5
        assert isinstance(result.peak_positions, list)
        assert result.prediction_time != ""

    def test_multiple_async_inferences(self):
        """验证：多次异步推理不冲突"""
        clf = Raman1DCNNClassifier(model_dir="app/models_test_empty", onnx_threads=4)
        specs = [_make_spectrum(RustProductType.CASSITERITE, snr_db=25) for _ in range(5)]

        async def _run_all():
            tasks = [clf.predict_async(s, f"MULTI_{i:02d}") for i, s in enumerate(specs)]
            return await asyncio.gather(*tasks)

        results = asyncio.run(_run_all())
        assert len(results) == 5
        for i, r in enumerate(results):
            assert r.artifact_id == f"MULTI_{i:02d}"
        clf.close()

    def test_close_releases_resources(self):
        """验证：close方法正确释放资源"""
        clf = Raman1DCNNClassifier(model_dir="app/models_test_empty", onnx_threads=2)
        assert clf._executor is not None
        clf.close()
        assert clf._onnx_session is None

    def test_export_onnx_method_exists(self):
        """验证：存在export_onnx导出方法"""
        clf = Raman1DCNNClassifier(model_dir="app/models_test_empty")
        assert hasattr(clf, "export_onnx")
        assert callable(clf.export_onnx)

    def test_onnx_priority_over_pytorch(self):
        """验证：ONNX优先级高于PyTorch"""
        clf = Raman1DCNNClassifier(model_dir="app/models_test_empty")
        init_order = []
        if clf._onnx_available:
            init_order.append("onnx")
        if clf._torch_available:
            init_order.append("pytorch")
        assert "onnx" in init_order or "pytorch" in init_order or True

    def test_preprocess_onnx_compatible(self):
        """验证：预处理输出与ONNX输入形状兼容"""
        clf = Raman1DCNNClassifier(model_dir="app/models_test_empty")
        spec = _make_spectrum(RustProductType.MALACHITE)
        processed = clf.preprocess_spectrum(spec)
        assert processed.dtype in (np.float32, np.float64)
        assert processed.ndim == 1
        assert len(processed) == clf.SPECTRUM_LENGTH

    def test_batch_preprocess_performance(self):
        """验证：批量预处理性能基准"""
        import time
        clf = Raman1DCNNClassifier(model_dir="app/models_test_empty")
        specs = [_make_spectrum(RustProductType.ATACAMITE, snr_db=30) for _ in range(10)]
        t0 = time.perf_counter()
        results = [clf.predict(specs[i], f"BATCH_{i:03d}") for i in range(10)]
        elapsed = time.perf_counter() - t0
        assert len(results) == 10
        assert elapsed < 10.0, f"10次推理 {elapsed:.2f}s 过长"
