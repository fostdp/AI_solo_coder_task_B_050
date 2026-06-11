"""
缓蚀剂残留寿命预测微服务
订阅环境数据，每小时重新计算寿命，存入数据库 + Redis
暴露同步API供前端查询倒计时
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any

import numpy as np

from ..config import get_settings
from ..streams import RedisStreamManager, parse_stream_message
from ..algorithms.life_predictor import (
    InhibitorLifetimePredictor,
    LifetimePrediction,
    InhibitorType,
    get_life_status_chinese,
    get_life_status_color,
)

logger = logging.getLogger("life_predictor_service")
settings = get_settings()


class LifetimePredictorService:
    """缓蚀剂寿命预测微服务"""

    def __init__(self, stream_manager: Optional[RedisStreamManager] = None):
        self.stream_mgr = stream_manager
        self.predictor: Optional[InhibitorLifetimePredictor] = None
        self._running = False
        self._env_cache: Dict[str, List[Dict]] = {}
        self._spray_cache: Dict[str, Dict] = {}
        self._results_cache: Dict[str, Dict] = {}
        self._last_calc_time: Dict[str, datetime] = {}
        self._stats = {
            "total_predictions": 0,
            "need_respray_count": 0,
            "avg_remaining_days": 0.0,
            "last_hourly_run": None,
            "by_status": {"excellent": 0, "good": 0, "degrading": 0, "warning": 0, "expired": 0},
        }
        self._hourly_interval = 3600

    def _init_components(self):
        if self.predictor is None:
            try:
                self.predictor = InhibitorLifetimePredictor(
                    model_dir=settings.MODEL_DIR
                )
            except Exception as e:
                logger.error(f"Failed to init Lifetime Predictor: {e}")

    async def run_loop(self):
        """主循环：订阅环境数据 + 每小时批量重算"""
        self._init_components()

        tasks = [
            asyncio.create_task(self._subscribe_env_stream()),
            asyncio.create_task(self._hourly_recalc_loop()),
        ]

        logger.info("Lifetime Predictor service started")
        self._running = True

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            self._running = False
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        logger.info("Lifetime Predictor service stopped")

    async def _subscribe_env_stream(self):
        """订阅环境数据stream"""
        if not self.stream_mgr:
            while self._running:
                await asyncio.sleep(60)
            return

        stream_name = settings.REDIS_STREAMS.get("raw_data", "stream:raw_data")
        group_name = settings.REDIS_GROUPS.get("life_predictor", "group:life_predictor")

        try:
            await self.stream_mgr.ensure_stream(stream_name)
            await self.stream_mgr.ensure_group(stream_name, group_name)
        except Exception as e:
            logger.warning(f"Stream setup: {e}")

        while self._running:
            try:
                messages = await self.stream_mgr.consume_group(
                    stream_name=stream_name,
                    group_name=group_name,
                    consumer_name="life_consumer_1",
                    count=10,
                    block_ms=3000,
                )
                if messages:
                    for msg in messages:
                        parsed = parse_stream_message(msg)
                        msg_type = parsed.get("type", "")
                        if msg_type == "microenvironment":
                            d = parsed.get("data", {})
                            aid = d.get("artifact_id")
                            if aid:
                                if aid not in self._env_cache:
                                    self._env_cache[aid] = []
                                self._env_cache[aid].append({
                                    "temperature": d.get("temperature", 22),
                                    "humidity": d.get("humidity", 50),
                                    "timestamp": d.get("timestamp", datetime.now().isoformat()),
                                })
                                if len(self._env_cache[aid]) > 24 * 7:
                                    self._env_cache[aid] = self._env_cache[aid][-24 * 7:]
                        try:
                            await self.stream_mgr.xack(stream_name, group_name, parsed["_id"])
                        except Exception:
                            pass
                await asyncio.sleep(0.2)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Env subscribe error: {e}")
                await asyncio.sleep(5)

    async def _hourly_recalc_loop(self):
        """每小时批量重新计算寿命"""
        while self._running:
            try:
                await self._recalculate_all()
                self._stats["last_hourly_run"] = datetime.now().isoformat()
                logger.info(f"Hourly lifetime recalculation complete: {self._stats['total_predictions']} artifacts")
            except Exception as e:
                logger.error(f"Hourly recalc error: {e}")
            for _ in range(self._hourly_interval):
                if not self._running:
                    break
                await asyncio.sleep(1)

    async def _recalculate_all(self):
        """对所有缓存的器物重算寿命"""
        artifact_ids = set(list(self._env_cache.keys()) + list(self._spray_cache.keys()))
        if not artifact_ids:
            artifact_ids = {f"BRZ{i:05d}" for i in range(1, 21)}

        for aid in artifact_ids:
            result = self.predict_sync(
                artifact_id=aid,
                inhibitor_type=InhibitorType.BTA,
                env_history=self._env_cache.get(aid, []),
            )
            if result:
                self._results_cache[aid] = {
                    "artifact_id": result.artifact_id,
                    "inhibitor_type": result.inhibitor_type.value,
                    "remaining_days": result.remaining_days,
                    "effectiveness": result.effectiveness,
                    "degradation_rate": result.degradation_rate,
                    "status": result.status.value,
                    "status_name": get_life_status_chinese(result.status),
                    "status_color": get_life_status_color(result.status),
                    "last_spray_date": result.last_spray_date,
                    "average_temp_7d": result.average_temp_7d,
                    "average_rh_7d": result.average_rh_7d,
                    "need_respray": result.need_respray,
                    "warning_level": result.warning_level,
                    "prediction_time": result.prediction_time,
                    "detail": result.detail,
                }
                self._update_stats(result)

    def predict_sync(
        self,
        artifact_id: str,
        inhibitor_type: InhibitorType = InhibitorType.BTA,
        env_history: Optional[List[Dict]] = None,
        last_spray_date: Optional[str] = None,
        initial_coverage: Optional[float] = None,
    ) -> Optional[LifetimePrediction]:
        """同步预测接口（供HTTP API调用）"""
        self._init_components()
        if self.predictor is None:
            return None

        env = env_history if env_history is not None else self._env_cache.get(artifact_id, [])
        spray = last_spray_date or self._spray_cache.get(artifact_id, {}).get("last_spray_date")
        cov = initial_coverage or self._spray_cache.get(artifact_id, {}).get("initial_coverage")

        return self.predictor.predict_from_timeseries(
            artifact_id=artifact_id,
            inhibitor_type=inhibitor_type,
            env_history=env,
            last_spray_date=spray,
            initial_coverage=cov,
        )

    def get_all_results(self) -> List[Dict]:
        """获取所有器物的寿命预测结果"""
        return list(self._results_cache.values())

    def get_result(self, artifact_id: str) -> Optional[Dict]:
        """获取单器物寿命结果"""
        return self._results_cache.get(artifact_id)

    def _update_stats(self, result: LifetimePrediction):
        self._stats["total_predictions"] += 1
        if result.need_respray:
            self._stats["need_respray_count"] += 1
        n = self._stats["total_predictions"]
        self._stats["avg_remaining_days"] = round(
            ((n - 1) * self._stats["avg_remaining_days"] + result.remaining_days) / n, 1
        )
        st = result.status.value
        if st in self._stats["by_status"]:
            self._stats["by_status"][st] += 1

    def get_stats(self) -> Dict:
        return dict(self._stats)

    def stop(self):
        self._running = False
