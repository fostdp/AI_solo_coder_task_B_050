"""
微服务编排器 (Microservice Orchestrator)
在单一进程内编排所有 9 个微服务，通过 Redis Stream 通信
保持向后兼容：现有 MQTTDataProcessor 的功能全部保留
"""

import asyncio
import logging
from typing import Optional, Dict, List

from ..config import get_settings
from ..streams import RedisStreamManager
from .mqtt_ingest import MQTTIngestService
from .feature_extractor import FeatureExtractorService
from .predictor import PredictorService
from .optimizer import SprayOptimizerService
from .alert_ws import AlertWSService, WebSocketManager
from .raman_service import RamanAnalysisService
from .life_predictor_service import LifetimePredictorService
from .ahp_scorer_service import VulnerabilityScorerService
from .ga_planner_service import GASprayPlannerService

logger = logging.getLogger("microservice_orchestrator")
settings = get_settings()


class MicroserviceOrchestrator:
    """微服务编排器 - 统一管理所有微服务的生命周期"""

    def __init__(self, use_stream: bool = True):
        self.use_stream = use_stream
        self.stream_mgr: Optional[RedisStreamManager] = None

        self.mqtt_ingest: Optional[MQTTIngestService] = None
        self.feature_extractor: Optional[FeatureExtractorService] = None
        self.predictor: Optional[PredictorService] = None
        self.optimizer: Optional[SprayOptimizerService] = None
        self.alert_ws: Optional[AlertWSService] = None
        self.raman: Optional[RamanAnalysisService] = None
        self.life_predictor: Optional[LifetimePredictorService] = None
        self.ahp_scorer: Optional[VulnerabilityScorerService] = None
        self.ga_planner: Optional[GASprayPlannerService] = None

        self._tasks: List[asyncio.Task] = []
        self._running = False

    async def start(self):
        """启动所有微服务"""
        logger.info("Starting microservice orchestrator (9 services)...")

        if self.use_stream:
            self.stream_mgr = RedisStreamManager(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                db=settings.REDIS_DB
            )
            await self.stream_mgr.connect()

        self.mqtt_ingest = MQTTIngestService(stream_manager=self.stream_mgr)
        self.feature_extractor = FeatureExtractorService(stream_manager=self.stream_mgr)
        self.predictor = PredictorService(stream_manager=self.stream_mgr)
        self.optimizer = SprayOptimizerService(stream_manager=self.stream_mgr)
        self.alert_ws = AlertWSService(stream_manager=self.stream_mgr)
        self.raman = RamanAnalysisService(stream_manager=self.stream_mgr)
        self.life_predictor = LifetimePredictorService(stream_manager=self.stream_mgr)
        self.ahp_scorer = VulnerabilityScorerService(stream_manager=self.stream_mgr)
        self.ga_planner = GASprayPlannerService(stream_manager=self.stream_mgr)

        self.mqtt_ingest.connect_and_subscribe()

        if self.use_stream and self.stream_mgr:
            self._tasks.append(asyncio.create_task(self.feature_extractor.run_loop()))
            self._tasks.append(asyncio.create_task(self.predictor.run_loop()))
            self._tasks.append(asyncio.create_task(self.optimizer.run_loop()))
            self._tasks.append(asyncio.create_task(self.alert_ws.run_loop()))
            self._tasks.append(asyncio.create_task(self.raman.run_loop()))
            self._tasks.append(asyncio.create_task(self.life_predictor.run_loop()))
            self._tasks.append(asyncio.create_task(self.ahp_scorer.run_loop()))
            self._tasks.append(asyncio.create_task(self.ga_planner.run_loop()))

        self._running = True
        logger.info("All 9 microservices started successfully")

    async def stop(self):
        """停止所有微服务"""
        self._running = False

        for task in self._tasks:
            task.cancel()

        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []

        if self.mqtt_ingest:
            self.mqtt_ingest.disconnect()
        for svc in [self.raman, self.life_predictor, self.ahp_scorer, self.ga_planner]:
            if svc:
                svc.stop()

        if self.stream_mgr:
            await self.stream_mgr.close()

        logger.info("All microservices stopped")

    def get_service_status(self) -> Dict:
        """获取所有服务状态"""
        return {
            "orchestrator_running": self._running,
            "stream_enabled": self.use_stream,
            "mqtt_ingest": {
                "connected": self.mqtt_ingest._mqtt_connected if self.mqtt_ingest else False,
                "cached_ecn": len(self.mqtt_ingest.last_ecn_data) if self.mqtt_ingest else 0,
                "cached_menv": len(self.mqtt_ingest.last_menv_data) if self.mqtt_ingest else 0
            },
            "feature_extractor": self.feature_extractor.get_stats() if self.feature_extractor else {},
            "predictor": self.predictor.get_stats() if self.predictor else {},
            "optimizer": self.optimizer.get_stats() if self.optimizer else {},
            "alert_ws": self.alert_ws.get_stats() if self.alert_ws else {},
            "raman": self.raman.get_stats() if self.raman else {},
            "life_predictor": self.life_predictor.get_stats() if self.life_predictor else {},
            "ahp_scorer": self.ahp_scorer.get_stats() if self.ahp_scorer else {},
            "ga_planner": self.ga_planner.get_stats() if self.ga_planner else {},
        }

    @property
    def ws_manager(self) -> Optional[WebSocketManager]:
        if self.alert_ws:
            return self.alert_ws.ws_mgr
        return None


_orchestrator: Optional[MicroserviceOrchestrator] = None


async def get_orchestrator() -> MicroserviceOrchestrator:
    """获取单例编排器"""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = MicroserviceOrchestrator()
        await _orchestrator.start()
    return _orchestrator
