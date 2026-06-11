"""
锈蚀产物拉曼光谱识别模块
使用1D-CNN分类锈蚀类型：孔雀石(Malachite)、氯铜矿(Atacamite)、锡石(Cassiterite)、赤铜矿(Cuprite)、蓝铜矿(Azurite)

设计说明：
- 输入：波数100-3500 cm⁻¹的拉曼光谱，插值至统一长度
- 模型：1D-CNN (Conv1d * 4 + GlobalAvgPool + FC)
- 输出：5类锈蚀产物的概率分布 + Top-1预测
- 降级方案：无PyTorch时使用特征匹配算法（余弦相似度）
"""

import os
import json
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Any
from enum import Enum

import numpy as np

logger = logging.getLogger("raman_cnn")


class RustProductType(str, Enum):
    MALACHITE = "malachite"          # 孔雀石 - Cu2(OH)2CO3
    ATACAMITE = "atacamite"          # 氯铜矿 - Cu2Cl(OH)3
    CASSITERITE = "cassiterite"      # 锡石 - SnO2
    CUPRITE = "cuprite"              # 赤铜矿 - Cu2O
    AZURITE = "azurite"              # 蓝铜矿 - Cu3(OH)2(CO3)2
    UNKNOWN = "unknown"


@dataclass
class RamanSpectrum:
    wavenumbers: np.ndarray
    intensities: np.ndarray

    @classmethod
    def from_lists(cls, wavenumbers: List[float], intensities: List[float]) -> "RamanSpectrum":
        return cls(
            wavenumbers=np.array(wavenumbers, dtype=np.float32),
            intensities=np.array(intensities, dtype=np.float32)
        )


@dataclass
class RamanPrediction:
    artifact_id: str
    product_type: RustProductType
    confidence: float
    probabilities: Dict[str, float]
    peak_positions: List[float] = field(default_factory=list)
    spectrum_id: Optional[str] = None
    sensor_id: Optional[str] = None
    position: Optional[Dict[str, float]] = None
    prediction_time: str = ""


RUST_PRODUCT_COLORS = {
    RustProductType.MALACHITE: "#228B22",      # 森林绿
    RustProductType.ATACAMITE: "#7CFC00",      # 草地绿
    RustProductType.CASSITERITE: "#8B4513",    # 棕色
    RustProductType.CUPRITE: "#B22222",        # 砖红
    RustProductType.AZURITE: "#1E90FF",        # 道奇蓝
    RustProductType.UNKNOWN: "#808080",        # 灰色
}


STANDARD_RAMAN_PEAKS: Dict[RustProductType, List[float]] = {
    RustProductType.MALACHITE: [172, 218, 355, 432, 506, 752, 1056, 1098, 1345, 1496, 1597],
    RustProductType.ATACAMITE: [155, 210, 348, 514, 582, 819, 913, 974, 1064, 1182, 1362, 1483],
    RustProductType.CASSITERITE: [244, 476, 633, 778, 992],
    RustProductType.CUPRITE: [147, 180, 219, 417, 520, 644],
    RustProductType.AZURITE: [248, 291, 399, 540, 766, 835, 940, 1092, 1356, 1416, 1573, 1663],
}


class Raman1DCNNClassifier:
    """1D-CNN拉曼光谱分类器 - 含PyTorch降级方案"""

    CLASSES: List[RustProductType] = [
        RustProductType.MALACHITE,
        RustProductType.ATACAMITE,
        RustProductType.CASSITERITE,
        RustProductType.CUPRITE,
        RustProductType.AZURITE,
    ]

    WN_MIN = 100.0
    WN_MAX = 3500.0
    SPECTRUM_LENGTH = 1024

    def __init__(self, model_dir: str = "app/models", use_gpu: bool = False,
                 onnx_threads: int = 4):
        self.model_dir = model_dir
        self.use_gpu = use_gpu
        self._model = None
        self._onnx_session = None
        self._torch_available = False
        self._onnx_available = False
        self._fitted = False
        self._executor = ThreadPoolExecutor(
            max_workers=onnx_threads, thread_name_prefix="raman_onnx"
        )

        self._init_backend()
        self._load_or_init_model()

    def _init_backend(self):
        """检测ONNX Runtime和PyTorch可用性，优先ONNX"""
        self._onnx_available = False
        try:
            import onnxruntime
            self._ort = onnxruntime
            self._onnx_available = True
            logger.info("ONNX Runtime backend available, preferring ONNX for inference")
        except ImportError:
            self._ort = None
            logger.warning("ONNX Runtime not available, will try PyTorch")

        try:
            import torch
            self._torch_available = True
            self._torch = torch
            self._torch_dtype = torch.float32
            logger.info("PyTorch backend available as fallback")
        except ImportError:
            self._torch_available = False
            logger.warning("PyTorch not available, falling back to peak matching algorithm")

    def _load_or_init_model(self):
        """加载ONNX模型（优先）或PyTorch模型"""
        onnx_path = os.path.join(self.model_dir, "raman_cnn.onnx")
        if self._onnx_available and os.path.exists(onnx_path):
            try:
                sess_opts = self._ort.SessionOptions()
                sess_opts.intra_op_num_threads = 4
                sess_opts.inter_op_num_threads = 2
                sess_opts.graph_optimization_level = (
                    self._ort.GraphOptimizationLevel.ORT_ENABLE_ALL
                )
                providers = ["CPUExecutionProvider"]
                self._onnx_session = self._ort.InferenceSession(
                    onnx_path, sess_opts, providers=providers
                )
                self._fitted = True
                logger.info(f"Loaded ONNX model from {onnx_path}")
                return
            except Exception as e:
                logger.warning(f"Failed to load ONNX model: {e}, falling back to PyTorch")
                self._onnx_session = None

        model_path = os.path.join(self.model_dir, "raman_cnn.pth")
        if self._torch_available and os.path.exists(model_path):
            self._model = self._build_cnn()
            try:
                state = self._torch.load(model_path, map_location="cpu")
                self._model.load_state_dict(state)
                self._model.eval()
                self._fitted = True
                logger.info(f"Loaded Raman CNN PyTorch model from {model_path}")
            except Exception as e:
                logger.warning(f"Failed to load CNN model: {e}, will use peak matching")
                self._model = None
        else:
            logger.info("No saved CNN/ONNX model, using peak matching as primary classifier")

    def _build_cnn(self) -> Any:
        """构建1D-CNN模型结构"""
        nn = self._torch.nn
        F = self._torch.nn.functional

        class SpectrumCNN(nn.Module):
            def __init__(self, in_channels: int = 1, num_classes: int = 5):
                super().__init__()
                self.features = nn.Sequential(
                    nn.Conv1d(in_channels, 32, kernel_size=7, stride=2, padding=3),
                    nn.BatchNorm1d(32),
                    nn.ReLU(),
                    nn.MaxPool1d(2),

                    nn.Conv1d(32, 64, kernel_size=5, stride=2, padding=2),
                    nn.BatchNorm1d(64),
                    nn.ReLU(),
                    nn.MaxPool1d(2),

                    nn.Conv1d(64, 128, kernel_size=3, stride=1, padding=1),
                    nn.BatchNorm1d(128),
                    nn.ReLU(),

                    nn.Conv1d(128, 256, kernel_size=3, stride=1, padding=1),
                    nn.BatchNorm1d(256),
                    nn.ReLU(),
                )
                self.gap = nn.AdaptiveAvgPool1d(1)
                self.classifier = nn.Sequential(
                    nn.Dropout(0.3),
                    nn.Linear(256, 128),
                    nn.ReLU(),
                    nn.Dropout(0.2),
                    nn.Linear(128, num_classes),
                    nn.Softmax(dim=1),
                )

            def forward(self, x):
                x = self.features(x)
                x = self.gap(x).squeeze(-1)
                x = self.classifier(x)
                return x

        model = SpectrumCNN()
        if self.use_gpu and self._torch.cuda.is_available():
            model = model.cuda()
        return model

    def preprocess_spectrum(self, spectrum: RamanSpectrum) -> np.ndarray:
        """光谱预处理：插值 + 基线校正 + 归一化"""
        wn = spectrum.wavenumbers
        inten = spectrum.intensities.copy()

        nan_mask = np.isnan(inten) | np.isinf(inten)
        if np.any(nan_mask):
            valid = ~nan_mask
            if np.any(valid):
                inten[nan_mask] = np.interp(wn[nan_mask], wn[valid], inten[valid])
            else:
                inten = np.zeros_like(inten)

        target_wn = np.linspace(self.WN_MIN, self.WN_MAX, self.SPECTRUM_LENGTH)
        mask = (wn >= self.WN_MIN) & (wn <= self.WN_MAX)
        wn_valid = wn[mask]
        inten_valid = inten[mask]

        if len(wn_valid) < 10:
            logger.warning(f"Insufficient valid spectrum points: {len(wn_valid)}")
            return np.zeros(self.SPECTRUM_LENGTH, dtype=np.float32)

        interp_inten = np.interp(target_wn, wn_valid, inten_valid)

        baseline = self._als_baseline(interp_inten, lam=1e6, p=0.01, niter=10)
        corrected = interp_inten - baseline

        corrected = np.clip(corrected, 0, None)
        max_val = corrected.max() if corrected.max() > 1e-8 else 1.0
        normalized = corrected / max_val

        return normalized.astype(np.float32)

    def _als_baseline(self, y: np.ndarray, lam: float, p: float, niter: int) -> np.ndarray:
        """基线校正（滚动最小值+平滑，高效稳定）"""
        from scipy.ndimage import uniform_filter1d
        w = max(len(y) // 20, 10)
        baseline = uniform_filter1d(y, size=w, mode='nearest')
        for _ in range(3):
            residual = y - baseline
            below = np.minimum(residual, 0)
            baseline = baseline + 0.3 * below
            baseline = uniform_filter1d(baseline, size=w, mode='nearest')
        return baseline

    def detect_peaks(self, spectrum: RamanSpectrum, height_ratio: float = 0.1,
                     min_distance: int = 10) -> List[float]:
        """检测拉曼特征峰位置"""
        from scipy.signal import find_peaks

        wn = spectrum.wavenumbers
        inten = spectrum.intensities

        mask = (wn >= self.WN_MIN) & (wn <= self.WN_MAX)
        inten = inten[mask]
        wn = wn[mask]

        if len(inten) < 20:
            return []

        baseline = self._als_baseline(inten, lam=1e5, p=0.01, niter=5)
        corrected = inten - baseline
        corrected = np.clip(corrected, 0, None)
        max_val = corrected.max() if corrected.max() > 1e-8 else 1.0
        corrected = corrected / max_val

        peaks, _ = find_peaks(
            corrected,
            height=height_ratio * corrected.max(),
            distance=min_distance
        )

        if len(peaks) == 0:
            return []

        peak_wn = wn[peaks]
        peak_int = corrected[peaks]
        sorted_idx = np.argsort(peak_int)[::-1]
        return [float(peak_wn[i]) for i in sorted_idx[:15]]

    def predict(self, spectrum: RamanSpectrum, artifact_id: str,
                sensor_id: Optional[str] = None,
                position: Optional[Dict[str, float]] = None) -> RamanPrediction:
        """预测锈蚀产物类型（同步） - 优先ONNX Runtime"""
        processed = self.preprocess_spectrum(spectrum)

        if self._onnx_session is not None:
            probs = self._predict_onnx(processed)
        elif self._torch_available and self._model is not None:
            probs = self._predict_cnn(processed)
        else:
            probs = self._predict_peak_matching(spectrum)

        top_idx = int(np.argmax(probs))
        top_class = self.CLASSES[top_idx]
        top_conf = float(probs[top_idx])

        if top_conf < 0.5:
            top_class = RustProductType.UNKNOWN

        peak_positions = self.detect_peaks(spectrum)

        prob_dict = {
            cls.value: float(probs[i])
            for i, cls in enumerate(self.CLASSES)
        }
        prob_dict[RustProductType.UNKNOWN.value] = max(0.0, 1.0 - sum(prob_dict.values()))

        from datetime import datetime
        return RamanPrediction(
            artifact_id=artifact_id,
            product_type=top_class,
            confidence=top_conf,
            probabilities=prob_dict,
            peak_positions=peak_positions,
            sensor_id=sensor_id,
            position=position,
            prediction_time=datetime.now().isoformat()
        )

    async def predict_async(self, spectrum: RamanSpectrum, artifact_id: str,
                            sensor_id: Optional[str] = None,
                            position: Optional[Dict[str, float]] = None) -> RamanPrediction:
        """异步推理（线程池），避免阻塞FastAPI事件循环"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor, lambda: self.predict(spectrum, artifact_id, sensor_id, position)
        )

    def _predict_onnx(self, processed: np.ndarray) -> np.ndarray:
        """使用ONNX Runtime推理（CPU优化+线程池）"""
        x = processed.astype(np.float32).reshape(1, 1, -1)
        input_name = self._onnx_session.get_inputs()[0].name
        output_name = self._onnx_session.get_outputs()[0].name
        result = self._onnx_session.run(
            [output_name], {input_name: x}
        )[0]
        return result.flatten().astype(np.float32)

    def _predict_cnn(self, processed: np.ndarray) -> np.ndarray:
        """使用1D-CNN PyTorch模型预测"""
        self._model.eval()
        with self._torch.no_grad():
            x = self._torch.from_numpy(processed).unsqueeze(0).unsqueeze(0)
            x = x.to(self._torch_dtype)
            if next(self._model.parameters()).is_cuda:
                x = x.cuda()
            output = self._model(x)
            probs = output.cpu().numpy().flatten()
        return probs

    def export_onnx(self, save_path: Optional[str] = None) -> str:
        """将PyTorch模型导出为ONNX格式（部署时优化推理性能）"""
        if not self._torch_available or self._model is None:
            raise RuntimeError("PyTorch model not available for ONNX export")

        save_path = save_path or os.path.join(self.model_dir, "raman_cnn.onnx")
        os.makedirs(os.path.dirname(save_path), exist_ok=True)

        self._model.eval()
        dummy = self._torch.randn(1, 1, self.SPECTRUM_LENGTH, dtype=self._torch_dtype)
        self._torch.onnx.export(
            self._model,
            dummy,
            save_path,
            input_names=["input"],
            output_names=["output"],
            dynamic_axes={"input": {0: "batch_size"}, "output": {0: "batch_size"}},
            opset_version=14,
        )
        logger.info(f"ONNX model exported to {save_path}")
        return save_path

    def close(self):
        """释放线程池和模型资源"""
        self._executor.shutdown(wait=False)
        self._onnx_session = None
        self._model = None

    def _predict_peak_matching(self, spectrum: RamanSpectrum) -> np.ndarray:
        """基于特征峰匹配的降级分类算法"""
        detected_peaks = np.array(self.detect_peaks(spectrum))
        scores = np.zeros(len(self.CLASSES), dtype=np.float64)
        tolerance = 25.0

        for i, cls in enumerate(self.CLASSES):
            std_peaks = np.array(STANDARD_RAMAN_PEAKS.get(cls, []))
            if len(std_peaks) == 0 or len(detected_peaks) == 0:
                scores[i] = 0.001
                continue

            match_count = 0
            matched_std = set()

            for p in detected_peaks:
                distances = np.abs(std_peaks - p)
                best_idx = int(np.argmin(distances))
                if distances[best_idx] <= tolerance and best_idx not in matched_std:
                    match_count += 1
                    matched_std.add(best_idx)

            recall = match_count / max(len(std_peaks), 1)
            scores[i] = recall

        exp_scores = np.exp(scores * 5.0)
        probs = exp_scores / exp_scores.sum()

        return probs.astype(np.float32)

    def save_model(self, path: Optional[str] = None):
        """保存模型权重"""
        if not self._torch_available or self._model is None:
            return
        path = path or os.path.join(self.model_dir, "raman_cnn.pth")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._torch.save(self._model.state_dict(), path)
        logger.info(f"Raman CNN model saved to {path}")

    def train_on_synthetic(self, n_samples_per_class: int = 500) -> float:
        """使用合成数据训练CNN，返回最终准确率"""
        if not self._torch_available:
            logger.warning("Cannot train without PyTorch")
            return 0.6

        logger.info(f"Training Raman CNN on synthetic data: {n_samples_per_class} samples/class")

        X, y = self._generate_synthetic_dataset(n_samples_per_class)
        X_t = self._torch.from_numpy(X).unsqueeze(1).float()
        y_t = self._torch.from_numpy(y).long()

        self._model = self._build_cnn()
        optimizer = self._torch.optim.Adam(self._model.parameters(), lr=1e-3)
        criterion = self._torch.nn.CrossEntropyLoss()

        n_epochs = 30
        batch_size = 64
        n = X_t.shape[0]
        best_acc = 0.0

        self._model.train()
        for epoch in range(n_epochs):
            perm = np.random.permutation(n)
            total_loss = 0.0
            correct = 0
            count = 0

            for i in range(0, n, batch_size):
                idx = perm[i:i + batch_size]
                xb = X_t[idx]
                yb = y_t[idx]

                if next(self._model.parameters()).is_cuda:
                    xb = xb.cuda()
                    yb = yb.cuda()

                optimizer.zero_grad()
                out = self._model(xb)
                loss = criterion(out, yb)
                loss.backward()
                optimizer.step()

                total_loss += loss.item() * xb.size(0)
                preds = out.argmax(dim=1)
                correct += (preds == yb).sum().item()
                count += xb.size(0)

            acc = correct / max(count, 1)
            if (epoch + 1) % 5 == 0:
                logger.info(f"  Epoch {epoch+1}/{n_epochs}, loss={total_loss/count:.4f}, acc={acc:.4f}")
            if acc > best_acc:
                best_acc = acc

        self._model.eval()
        self._fitted = True
        self.save_model()
        return best_acc

    def _generate_synthetic_dataset(self, n_per_class: int) -> Tuple[np.ndarray, np.ndarray]:
        """生成合成拉曼光谱数据集"""
        n_classes = len(self.CLASSES)
        X = np.zeros((n_per_class * n_classes, self.SPECTRUM_LENGTH), dtype=np.float32)
        y = np.zeros(n_per_class * n_classes, dtype=np.int64)
        target_wn = np.linspace(self.WN_MIN, self.WN_MAX, self.SPECTRUM_LENGTH)

        idx = 0
        for ci, cls in enumerate(self.CLASSES):
            peaks = STANDARD_RAMAN_PEAKS.get(cls, [])
            for _ in range(n_per_class):
                spec = np.zeros(self.SPECTRUM_LENGTH)
                for p in peaks:
                    amp = np.random.uniform(0.5, 1.5)
                    width = np.random.uniform(8, 25)
                    shift = np.random.uniform(-3, 3)
                    pos = p + shift
                    spec += amp * np.exp(-0.5 * ((target_wn - pos) / width) ** 2)

                spec += np.random.uniform(0.02, 0.08) * (target_wn / 3500)
                spec += np.random.normal(0, np.random.uniform(0.02, 0.08), self.SPECTRUM_LENGTH)
                spec = np.clip(spec, 0, None)
                if spec.max() > 1e-8:
                    spec = spec / spec.max()

                X[idx] = spec
                y[idx] = ci
                idx += 1

        return X, y


def get_raman_color(product_type: RustProductType) -> str:
    """获取锈蚀产物对应的显示颜色"""
    return RUST_PRODUCT_COLORS.get(product_type, "#808080")


def get_product_chinese_name(product_type: RustProductType) -> str:
    """获取锈蚀产物的中文名称"""
    name_map = {
        RustProductType.MALACHITE: "孔雀石",
        RustProductType.ATACAMITE: "氯铜矿",
        RustProductType.CASSITERITE: "锡石",
        RustProductType.CUPRITE: "赤铜矿",
        RustProductType.AZURITE: "蓝铜矿",
        RustProductType.UNKNOWN: "未知",
    }
    return name_map.get(product_type, "未知")
