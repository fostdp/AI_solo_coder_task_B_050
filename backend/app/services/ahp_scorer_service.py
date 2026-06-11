"""
文物脆弱性综合评分微服务
基于层次分析法(AHP)融合多维指标，每12小时批量重算，供前端热力图展示
"""

import asyncio
import json
import logging
import random
from datetime import datetime
from typing import Optional, Dict, List, Any

from ..config import get_settings
from ..streams import RedisStreamManager, parse_stream_message
from ..algorithms.ahp_scorer import (
    AHPScorer,
    ArtifactVulnerabilityData,
    VulnerabilityScore,
    VulnerabilityLevel,
    LEVEL_COLORS,
    LEVEL_NAMES,
    get_level_info,
)

logger = logging.getLogger("ahp_scorer_service")
settings = get_settings()


class VulnerabilityScorerService:
    """文物脆弱性综合评分微服务"""

    def __init__(self, stream_manager: Optional[RedisStreamManager] = None):
        self.stream_mgr = stream_manager
        self.scorer: Optional[AHPScorer] = None
        self._running = False
        self._artifact_data: Dict[str, ArtifactVulnerabilityData] = {}
        self._results_cache: Dict[str, Dict] = {}
        self._stats = {
            "total_scored": 0,
            "level_distribution": {e.value: 0 for e in VulnerabilityLevel},
            "avg_score": 0.0,
            "last_run": None,
        }
        self._recalc_interval = 3600 * 12

    def _init_components(self):
        if self.scorer is None:
            try:
                matrices = getattr(settings, "AHP_MATRICES", None)
                self.scorer = AHPScorer(config_matrices=matrices)
                self._seed_artifact_data()
            except Exception as e:
                logger.error(f"Failed to init AHP Scorer: {e}")

    def _seed_artifact_data(self):
        """初始化200件器物的模拟数据（CT结构参数、修复历史）"""
        if self._artifact_data:
            return
        rng = random.Random(42)
        for i in range(1, 201):
            aid = f"BRZ{i:05d}"
            self._artifact_data[aid] = ArtifactVulnerabilityData(
                artifact_id=aid,
                wall_thickness_uniformity=rng.uniform(0.7, 0.98),
                crack_index=rng.uniform(0.0, 0.4),
                deformation_degree=rng.uniform(0.0, 0.25),
                repair_count=rng.choices([0, 1, 2, 3, 5, 8], weights=[40, 25, 15, 10, 7, 3])[0],
                last_repair_years_ago=rng.uniform(0.5, 35.0),
                hall_x=rng.uniform(0, 10),
                hall_y=rng.uniform(0, 8),
            )
        logger.info(f"Seeded AHP data for {len(self._artifact_data)} artifacts")

    async def run_loop(self):
        self._init_components()

        tasks = [
            asyncio.create_task(self._subscribe_predictions()),
            asyncio.create_task(self._periodic_recalc_loop()),
        ]

        logger.info("AHP Vulnerability Scorer service started")
        self._running = True

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            self._running = False
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        logger.info("AHP Vulnerability Scorer stopped")

    async def _subscribe_predictions(self):
        """订阅预测结果，更新锈蚀风险指标"""
        if not self.stream_mgr:
            while self._running:
                await asyncio.sleep(60)
            return

        stream_name = settings.REDIS_STREAMS.get("predictions", "stream:predictions")
        group_name = settings.REDIS_GROUPS.get("ahp_scorer", "group:ahp_scorer")

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
                    consumer_name="ahp_consumer_1",
                    count=10,
                    block_ms=3000,
                )
                if messages:
                    for msg in messages:
                        try:
                            parsed = parse_stream_message(msg)
                            d = parsed.get("data", {})
                            if isinstance(d, str):
                                d = json.loads(d)
                            aid = d.get("artifact_id")
                            if aid and aid in self._artifact_data:
                                ad = self._artifact_data[aid]
                                ad.eruption_probability = float(d.get("eruption_probability", 0))
                                ad.risk_level = int(d.get("risk_level", 1))
                                env = d.get("microenv", {})
                                if env:
                                    ad.chloride_concentration = float(env.get("chloride_concentration", 1.0))
                            try:
                                await self.stream_mgr.xack(stream_name, group_name, parsed["_id"])
                            except Exception:
                                pass
                        except Exception as e:
                            logger.error(f"Prediction parse error: {e}")
                await asyncio.sleep(0.2)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"AHP subscribe error: {e}")
                await asyncio.sleep(5)

    async def _periodic_recalc_loop(self):
        """每12小时批量重算"""
        while self._running:
            try:
                await self._recalculate_all()
                self._stats["last_run"] = datetime.now().isoformat()
                logger.info(f"AHP periodic recalc complete: {self._stats['total_scored']} artifacts, avg={self._stats['avg_score']:.1f}")
            except Exception as e:
                logger.error(f"AHP periodic recalc error: {e}")
            for _ in range(self._recalc_interval):
                if not self._running:
                    break
                await asyncio.sleep(1)

    async def _recalculate_all(self):
        """批量重算所有器物"""
        all_data = list(self._artifact_data.values())
        if not all_data:
            return

        scores = self.scorer.batch_score(all_data)
        level_dist = {e.value: 0 for e in VulnerabilityLevel}
        total = 0.0

        for s in scores:
            self._results_cache[s.artifact_id] = {
                "artifact_id": s.artifact_id,
                "total_score": s.total_score,
                "level": s.level.value,
                "level_name": LEVEL_NAMES[s.level],
                "level_color": LEVEL_COLORS[s.level],
                "sub_scores": s.sub_scores,
                "criterion_contributions": s.criterion_contributions,
                "consistency_ratio": s.consistency_ratio,
                "hall_x": s.hall_x,
                "hall_y": s.hall_y,
                "calculation_time": s.calculation_time,
                "recommendations": s.recommendations,
            }
            level_dist[s.level.value] += 1
            total += s.total_score

        n = len(scores)
        self._stats["total_scored"] = n
        self._stats["level_distribution"] = level_dist
        self._stats["avg_score"] = round(total / max(n, 1), 1)

        if self.stream_mgr:
            try:
                heatmap_stream = settings.REDIS_STREAMS.get("vulnerability_results", "stream:vulnerability_results")
                await self.stream_mgr.ensure_stream(heatmap_stream)
                heatmap_data = self.scorer.export_heatmap_data(scores)
                await self.stream_mgr.publish(heatmap_stream, {
                    "type": "heatmap_update",
                    "data": json.dumps({"count": len(heatmap_data), "timestamp": datetime.now().isoformat()}),
                })
            except Exception as e:
                logger.warning(f"Failed to publish heatmap: {e}")

    def score_sync(self, artifact_id: str) -> Optional[Dict]:
        """同步评分单器物"""
        self._init_components()
        if not self.scorer:
            return None

        data = self._artifact_data.get(artifact_id)
        if not data:
            data = ArtifactVulnerabilityData(artifact_id=artifact_id)
            self._artifact_data[artifact_id] = data

        score = self.scorer.score(data)
        return {
            "artifact_id": score.artifact_id,
            "total_score": score.total_score,
            "level": score.level.value,
            "level_name": LEVEL_NAMES[score.level],
            "level_color": LEVEL_COLORS[score.level],
            "sub_scores": score.sub_scores,
            "criterion_contributions": score.criterion_contributions,
            "consistency_ratio": score.consistency_ratio,
            "calculation_time": score.calculation_time,
            "recommendations": score.recommendations,
        }

    def get_all_scores(self) -> List[Dict]:
        """获取所有评分结果"""
        return list(self._results_cache.values())

    def get_score(self, artifact_id: str) -> Optional[Dict]:
        """获取单器物评分"""
        if artifact_id in self._results_cache:
            return self._results_cache[artifact_id]
        return self.score_sync(artifact_id)

    def get_heatmap_data(self) -> List[Dict]:
        """获取热力图数据"""
        return [
            {
                "artifact_id": v["artifact_id"],
                "x": v["hall_x"],
                "y": v["hall_y"],
                "value": v["total_score"],
                "level": v["level"],
                "color": v["level_color"],
                "sub_scores": v["sub_scores"],
            }
            for v in self._results_cache.values()
        ]

    def get_stats(self) -> Dict:
        return dict(self._stats)

    def stop(self):
        self._running = False
