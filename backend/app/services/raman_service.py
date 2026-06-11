"""
拉曼光谱识别微服务
订阅 stream:raw_data 中的拉曼数据，调用 Raman1DCNNClassifier 识别锈蚀产物，
写入数据库 + 发布到 stream:raman_results
支持 HTTP API 同步识别
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional, Dict, List, Any

import numpy as np

from ..config import get_settings
from ..streams import RedisStreamManager, parse_stream_message
from ..algorithms.raman_cnn import (
    Raman1DCNNClassifier,
    RamanSpectrum,
    RamanPrediction,
    RustProductType,
    get_product_chinese_name,
    get_raman_color,
)

logger = logging.getLogger("raman_service")
settings = get_settings()


class RamanAnalysisService:
    """拉曼光谱识别微服务"""

    def __init__(self, stream_manager: Optional[RedisStreamManager] = None):
        self.stream_mgr = stream_manager
        self.classifier: Optional[Raman1DCNNClassifier] = None
        self._running = False
        self._stats = {
            "processed": 0,
            "malachite": 0,
            "atacamite": 0,
            "cassiterite": 0,
            "cuprite": 0,
            "azurite": 0,
            "unknown": 0,
            "avg_confidence": 0.0,
            "last_processed": None,
        }

    def _init_components(self):
        """初始化分类器组件"""
        if self.classifier is None:
            try:
                self.classifier = Raman1DCNNClassifier(
                    model_dir=settings.MODEL_DIR
                )
                try:
                    self.classifier.train_on_synthetic(n_samples_per_class=200)
                except Exception as e:
                    logger.warning(f"CNN training skipped, using peak matching: {e}")
            except Exception as e:
                logger.error(f"Failed to init Raman classifier: {e}")
                self.classifier = None

    async def run_loop(self):
        """主循环：消费 stream:raw_data 中的拉曼数据"""
        if not self.stream_mgr:
            logger.warning("Raman service: no stream manager, running in standalone mode")
            self._init_components()
            while self._running:
                await asyncio.sleep(30)
            return

        self._init_components()
        stream_name = settings.REDIS_STREAMS.get("raw_data", "stream:raw_data")
        group_name = settings.REDIS_GROUPS.get("raman_analysis", "group:raman_analysis")

        try:
            await self.stream_mgr.ensure_stream(stream_name)
            await self.stream_mgr.ensure_group(stream_name, group_name)
        except Exception as e:
            logger.warning(f"Stream setup warning: {e}")

        logger.info("Raman analysis service started")
        self._running = True

        while self._running:
            try:
                messages = await self.stream_mgr.consume_group(
                    stream_name=stream_name,
                    group_name=group_name,
                    consumer_name="raman_consumer_1",
                    count=5,
                    block_ms=2000,
                )

                if messages:
                    await self._process_messages(messages, stream_name, group_name)

                await asyncio.sleep(0.1)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Raman service error: {e}")
                await asyncio.sleep(5)

        logger.info("Raman analysis service stopped")

    async def _process_messages(self, messages, stream_name, group_name):
        """批量处理消息，过滤raman类型"""
        for msg in messages:
            try:
                parsed = parse_stream_message(msg)
                msg_type = parsed.get("type", "")
                if msg_type != "raman_spectrum":
                    await self.stream_mgr.xack(stream_name, group_name, parsed["_id"])
                    continue

                result = self.analyze_sync(parsed.get("data", {}))
                if result and self.stream_mgr:
                    raman_stream = settings.REDIS_STREAMS.get(
                        "raman_results", "stream:raman_results"
                    )
                    await self.stream_mgr.ensure_stream(raman_stream)
                    await self.stream_mgr.publish(raman_stream, {
                        "type": "raman_result",
                        "data": json.dumps({
                            "artifact_id": result.artifact_id,
                            "product_type": result.product_type.value,
                            "product_name": get_product_chinese_name(result.product_type),
                            "product_color": get_raman_color(result.product_type),
                            "confidence": result.confidence,
                            "probabilities": result.probabilities,
                            "peak_positions": result.peak_positions,
                            "sensor_id": result.sensor_id,
                            "position": result.position,
                            "prediction_time": result.prediction_time,
                        }),
                    })

                await self.stream_mgr.xack(stream_name, group_name, parsed["_id"])
                self._update_stats(result)

            except Exception as e:
                logger.error(f"Error processing Raman message: {e}")

    def analyze_sync(self, data: Dict[str, Any]) -> Optional[RamanPrediction]:
        """同步分析接口（供HTTP API调用）"""
        self._init_components()
        if self.classifier is None:
            logger.error("Raman classifier not available")
            return None

        try:
            wavenumbers = data.get("wavenumbers")
            intensities = data.get("intensities")
            artifact_id = data.get("artifact_id", "unknown")
            sensor_id = data.get("sensor_id")
            position = data.get("position")

            if wavenumbers is None or intensities is None:
                logger.warning("Missing wavenumbers/intensities in Raman data")
                return None

            spectrum = RamanSpectrum.from_lists(
                wavenumbers=wavenumbers,
                intensities=intensities,
            )

            return self.classifier.predict(
                spectrum=spectrum,
                artifact_id=artifact_id,
                sensor_id=sensor_id,
                position=position,
            )

        except Exception as e:
            logger.error(f"Raman analysis failed: {e}")
            return None

    async def analyze_async(self, data: Dict[str, Any]) -> Optional[RamanPrediction]:
        """异步分析接口（线程池推理，不阻塞FastAPI事件循环）"""
        self._init_components()
        if self.classifier is None:
            logger.error("Raman classifier not available")
            return None

        try:
            wavenumbers = data.get("wavenumbers")
            intensities = data.get("intensities")
            artifact_id = data.get("artifact_id", "unknown")
            sensor_id = data.get("sensor_id")
            position = data.get("position")

            if wavenumbers is None or intensities is None:
                logger.warning("Missing wavenumbers/intensities in Raman data")
                return None

            spectrum = RamanSpectrum.from_lists(
                wavenumbers=wavenumbers,
                intensities=intensities,
            )

            return await self.classifier.predict_async(
                spectrum=spectrum,
                artifact_id=artifact_id,
                sensor_id=sensor_id,
                position=position,
            )

        except Exception as e:
            logger.error(f"Raman async analysis failed: {e}")
            return None

    def _update_stats(self, result: RamanPrediction):
        self._stats["processed"] += 1
        t = result.product_type.value
        if t in self._stats:
            self._stats[t] += 1
        n = self._stats["processed"]
        self._stats["avg_confidence"] = round(
            ((n - 1) * self._stats["avg_confidence"] + result.confidence) / n, 4
        )
        self._stats["last_processed"] = datetime.now().isoformat()

    def get_stats(self) -> Dict:
        return dict(self._stats)

    def stop(self):
        self._running = False
