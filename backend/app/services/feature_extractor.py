"""
Feature Extractor Service (微服务2)
职责：
  1. 从 Redis Stream:raw_data 消费电化学噪声原始数据
  2. 小波包分解 (PyWavelets) 提取多尺度能量、熵特征
  3. PCA 降维 (sklearn)
  4. 发布特征向量到 Redis Stream:features

数据流：Redis Stream:raw_data -> 小波包 -> PCA -> Redis Stream:features
"""

import asyncio
import json
import logging
import os
import numpy as np
from datetime import datetime
from typing import Dict, Optional, List
from dataclasses import dataclass, field

from ..config import get_settings
from ..streams import RedisStreamManager, parse_stream_message
from ..algorithms.wavelet_features import WaveletPacketFeatureExtractor
from ..algorithms.pca_transformer import PCATransformer

logger = logging.getLogger("feature_extractor")
settings = get_settings()


@dataclass
class ExtractedFeatures:
    artifact_id: str
    sensor_id: str
    extracted_at: datetime
    statistical_features: Dict = field(default_factory=dict)
    band_energy_ratios: Dict = field(default_factory=dict)
    wavelet_entropy: float = 0.0
    noise_resistance: float = 0.0
    pitting_index: float = 0.0
    pca_features: List[float] = field(default_factory=list)
    raw_feature_count: int = 0
    pca_dimensions: int = 0


class FeatureExtractorService:
    """特征提取微服务"""

    def __init__(self, stream_manager: Optional[RedisStreamManager] = None):
        self.stream_mgr = stream_manager
        self._raw_stream = settings.REDIS_STREAM_RAW
        self._feature_stream = settings.REDIS_STREAM_FEATURES
        self._group = settings.REDIS_GROUP_FEATURE
        self._consumer_name = f"extractor_{os.getpid()}_{id(self)}"

        self.wavelet_extractor: Optional[WaveletPacketFeatureExtractor] = None
        self.pca: Optional[PCATransformer] = None
        self._running = False
        self._stats = {
            "processed": 0,
            "failed": 0,
            "last_ts": None
        }

    def _init_components(self):
        if self.wavelet_extractor is None:
            self.wavelet_extractor = WaveletPacketFeatureExtractor(
                wavelet=settings.WAVELET_TYPE,
                max_level=settings.WAVELET_MAX_LEVEL,
                sampling_rate=settings.WAVELET_SAMPLING_RATE
            )
            logger.info(
                f"Wavelet extractor initialized: "
                f"wavelet={settings.WAVELET_TYPE}, "
                f"level={settings.WAVELET_MAX_LEVEL}"
            )

        if self.pca is None:
            self.pca = PCATransformer(
                n_components=settings.PCA_COMPONENTS,
                model_dir=settings.MODEL_DIR
            )
            logger.info(
                f"PCA transformer initialized: n_components={settings.PCA_COMPONENTS}"
            )

    async def start(self):
        self._init_components()
        if self.stream_mgr:
            await self.stream_mgr.ensure_stream(self._raw_stream)
            await self.stream_mgr.ensure_stream(self._feature_stream)
            await self.stream_mgr.ensure_group(self._raw_stream, self._group)
        self._running = True
        logger.info("Feature Extractor service started")

    async def stop(self):
        self._running = False
        logger.info("Feature Extractor service stopped")

    async def run_loop(self):
        """主消费循环"""
        await self.start()
        while self._running:
            try:
                if not self.stream_mgr:
                    await asyncio.sleep(1)
                    continue

                messages = await self.stream_mgr.consume_group(
                    self._raw_stream,
                    self._group,
                    self._consumer_name,
                    count=10,
                    block_ms=2000
                )

                for stream_name, stream_msgs in messages:
                    for msg in stream_msgs:
                        try:
                            parsed = parse_stream_message(msg)
                            await self._process_message(parsed)
                            await self.stream_mgr.ack(
                                self._raw_stream, self._group, parsed["_id"]
                            )
                            self._stats["processed"] += 1
                            self._stats["last_ts"] = datetime.utcnow()
                        except Exception as e:
                            self._stats["failed"] += 1
                            logger.exception(f"Feature extraction failed: {e}")

                if not messages:
                    await asyncio.sleep(0.5)

            except Exception as e:
                logger.exception(f"Feature extractor loop error: {e}")
                await asyncio.sleep(1)

    async def _process_message(self, msg: Dict):
        """处理单条消息"""
        sensor_type = msg.get("sensor_type")
        payload = msg.get("payload")

        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                pass

        if not isinstance(payload, dict):
            logger.warning(f"Invalid payload format: {type(payload)}")
            return

        if sensor_type == "electrochemical":
            features = await self._extract_wavelet_features(payload)
            if features:
                await self._publish_features(features)
        else:
            logger.debug(f"Skipping non-ECN data: {sensor_type}")

    async def _extract_wavelet_features(self, payload: Dict) -> Optional[ExtractedFeatures]:
        """从小波包中提取特征 + PCA降维"""
        try:
            artifact_id = payload.get("artifact_id", "unknown")
            sensor_id = payload.get("sensor_id", "unknown")

            volt = np.array(payload.get("voltage_noise") or [0.0], dtype=np.float64)
            curr = np.array(payload.get("current_noise") or [0.0], dtype=np.float64)

            if len(volt) < 32 or len(curr) < 32:
                logger.debug(
                    f"Signal too short for wavelet: V={len(volt)}, I={len(curr)}"
                )
                return None

            raw_features = self.wavelet_extractor.extract(volt, curr)

            feat_vector, feat_names = self._build_feature_vector(raw_features, payload)
            raw_count = len(feat_vector)

            aligned = self._align_features_for_pca(feat_vector)
            pca_result = self.pca.transform(aligned)
            pca_features = pca_result.flatten().tolist()

            return ExtractedFeatures(
                artifact_id=artifact_id,
                sensor_id=sensor_id,
                extracted_at=datetime.utcnow(),
                statistical_features=raw_features.statistical_features,
                band_energy_ratios=raw_features.band_energy_ratios,
                wavelet_entropy=raw_features.wavelet_entropy,
                noise_resistance=raw_features.noise_resistance,
                pitting_index=raw_features.pitting_index,
                pca_features=pca_features,
                raw_feature_count=raw_count,
                pca_dimensions=len(pca_features)
            )

        except Exception as e:
            logger.exception(f"Wavelet feature extraction error: {e}")
            return None

    def _align_features_for_pca(self, feat_vector: np.ndarray) -> np.ndarray:
        """对齐特征维度以匹配 PCA 模型输入"""
        if self.pca is None or not self.pca._fitted:
            return feat_vector

        expected_dim = self.pca.pca.n_features_in_
        current_dim = feat_vector.shape[0] if len(feat_vector.shape) == 1 else feat_vector.shape[1]

        if current_dim == expected_dim:
            return feat_vector

        if len(feat_vector.shape) == 1:
            feat_vector = feat_vector.reshape(1, -1)

        if current_dim < expected_dim:
            pad = np.zeros((feat_vector.shape[0], expected_dim - current_dim))
            return np.hstack([feat_vector, pad])
        else:
            return feat_vector[:, :expected_dim]

    def _build_feature_vector(self, wavelet_features, payload: Dict) -> tuple:
        """构建特征向量（与模型训练时一致）"""
        feat_values = []
        feat_names = []

        statistical = wavelet_features.statistical_features or {}
        for k in sorted(statistical.keys()):
            feat_values.append(float(statistical[k]))
            feat_names.append(k)

        band_ratios = wavelet_features.band_energy_ratios or {}
        for k in sorted(band_ratios.keys()):
            feat_values.append(float(band_ratios[k]))
            feat_names.append(k)

        feat_values.append(float(wavelet_features.wavelet_entropy or 0.0))
        feat_names.append("wavelet_entropy")

        feat_values.append(np.log10(float(wavelet_features.noise_resistance or 1.0) + 1e-6))
        feat_names.append("log_noise_resistance")

        feat_values.append(float(wavelet_features.pitting_index or 0.0))
        feat_names.append("pitting_index")

        return np.array(feat_values, dtype=np.float64), feat_names

    async def _publish_features(self, features: ExtractedFeatures):
        """发布特征到 Stream"""
        if not self.stream_mgr:
            return

        data = {
            "artifact_id": features.artifact_id,
            "sensor_id": features.sensor_id,
            "extracted_at": features.extracted_at.isoformat(),
            "statistical_features": json.dumps(features.statistical_features),
            "band_energy_ratios": json.dumps(features.band_energy_ratios),
            "wavelet_entropy": features.wavelet_entropy,
            "noise_resistance": features.noise_resistance,
            "pitting_index": features.pitting_index,
            "pca_features": json.dumps(features.pca_features),
            "raw_feature_count": features.raw_feature_count,
            "pca_dimensions": features.pca_dimensions
        }

        msg_id = await self.stream_mgr.publish(self._feature_stream, data)
        logger.debug(
            f"Published features for {features.artifact_id}: "
            f"{features.pca_dimensions}D PCA -> {self._feature_stream} ({msg_id})"
        )

    def extract_sync(self, voltage: np.ndarray, current: np.ndarray,
                     artifact_id: str = "test") -> Optional[ExtractedFeatures]:
        """同步提取接口（用于测试/单步调用）"""
        self._init_components()

        class FakePayload:
            pass

        raw_features = self.wavelet_extractor.extract(voltage, current)
        feat_vector, feat_names = self._build_feature_vector(raw_features, {})
        aligned = self._align_features_for_pca(feat_vector)
        pca_result = self.pca.transform(aligned)

        return ExtractedFeatures(
            artifact_id=artifact_id,
            sensor_id="sync",
            extracted_at=datetime.utcnow(),
            statistical_features=raw_features.statistical_features,
            band_energy_ratios=raw_features.band_energy_ratios,
            wavelet_entropy=raw_features.wavelet_entropy,
            noise_resistance=raw_features.noise_resistance,
            pitting_index=raw_features.pitting_index,
            pca_features=pca_result.flatten().tolist(),
            raw_feature_count=len(feat_vector),
            pca_dimensions=pca_result.shape[1]
        )

    def get_stats(self) -> Dict:
        return {
            **self._stats,
            "is_running": self._running,
            "pca_fitted": self.pca._fitted if self.pca else False,
            "wavelet_type": settings.WAVELET_TYPE,
            "max_level": settings.WAVELET_MAX_LEVEL
        }
