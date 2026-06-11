"""
智能喷涂路径动态规划微服务
基于遗传算法(GA)优化喷涂机器人路径，每6小时重算，结果通过WebSocket推送
"""

import asyncio
import json
import logging
import random
from datetime import datetime
from typing import Optional, Dict, List, Any

from ..config import get_settings
from ..streams import RedisStreamManager, parse_stream_message
from ..algorithms.ga_planner import (
    GASprayPlanner,
    RustHotspot,
    RobotConfig,
    SprayPathPlan,
    RobotArmType,
    waypoints_to_dict,
)

logger = logging.getLogger("ga_planner_service")
settings = get_settings()


class GASprayPlannerService:
    """GA喷涂路径规划微服务"""

    def __init__(self, stream_manager: Optional[RedisStreamManager] = None):
        self.stream_mgr = stream_manager
        self.planner: Optional[GASprayPlanner] = None
        self._running = False
        self._hotspot_cache: Dict[str, List[RustHotspot]] = {}
        self._artifact_sizes: Dict[str, Dict[str, float]] = {}
        self._plans_cache: Dict[str, Dict] = {}
        self._stats = {
            "total_plans": 0,
            "avg_coverage": 0.0,
            "avg_planning_time_ms": 0.0,
            "last_run": None,
        }
        self._recalc_interval = 3600 * 6

    def _init_components(self):
        if self.planner is None:
            try:
                rc = RobotConfig(
                    arm_type=RobotArmType(getattr(settings, "GA_ROBOT_TYPE", "articulated")),
                    max_reach_m=getattr(settings, "GA_MAX_REACH", 0.8),
                    max_speed_m_s=getattr(settings, "GA_MAX_SPEED", 0.3),
                    spray_flow_rate_ml_s=getattr(settings, "GA_FLOW_RATE", 0.5),
                    optimal_distance_m=getattr(settings, "GA_OPT_DISTANCE", 0.15),
                    spray_angle_deg=getattr(settings, "GA_SPRAY_ANGLE", 45.0),
                    max_total_time_s=getattr(settings, "GA_MAX_TIME", 600.0),
                )
                self.planner = GASprayPlanner(config=rc)
                self._seed_demo_data()
            except Exception as e:
                logger.error(f"Failed to init GA Planner: {e}")

    def _seed_demo_data(self):
        """生成演示热点数据"""
        rng = random.Random(123)
        artifacts = [f"BRZ{i:05d}" for i in range(1, 11)]
        for aid in artifacts:
            w = rng.uniform(0.3, 0.6)
            h = rng.uniform(0.3, 0.8)
            d = rng.uniform(0.25, 0.5)
            self._artifact_sizes[aid] = {"width": w, "height": h, "depth": d}
            n_hs = rng.randint(3, 8)
            hotspots = []
            for j in range(n_hs):
                hotspots.append(RustHotspot(
                    hotspot_id=f"{aid}_HS{j:02d}",
                    x=rng.uniform(-w/2 * 0.8, w/2 * 0.8),
                    y=rng.uniform(-h/2 * 0.8, h/2 * 0.8),
                    z=rng.uniform(-d/2 * 0.8, d/2 * 0.8),
                    severity=rng.uniform(0.2, 0.95),
                    area_cm2=rng.uniform(2.0, 25.0),
                    surface_normal=(
                        rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(0.5, 1)
                    ),
                    required_coverage=rng.uniform(0.85, 0.98),
                ))
            self._hotspot_cache[aid] = hotspots
        logger.info(f"Seeded GA demo data for {len(self._hotspot_cache)} artifacts")

    async def run_loop(self):
        self._init_components()

        tasks = [
            asyncio.create_task(self._subscribe_predictions()),
            asyncio.create_task(self._periodic_planning_loop()),
        ]

        logger.info("GA Spray Planner service started")
        self._running = True

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            self._running = False
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        logger.info("GA Spray Planner stopped")

    async def _subscribe_predictions(self):
        """订阅预测结果，更新热点"""
        if not self.stream_mgr:
            while self._running:
                await asyncio.sleep(60)
            return

        stream_name = settings.REDIS_STREAMS.get("predictions", "stream:predictions")
        group_name = settings.REDIS_GROUPS.get("ga_planner", "group:ga_planner")

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
                    consumer_name="ga_consumer_1",
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
                            risk_zones = d.get("risk_zones", [])
                            if aid and risk_zones:
                                self._update_hotspots_from_prediction(aid, risk_zones)
                            try:
                                await self.stream_mgr.xack(stream_name, group_name, parsed["_id"])
                            except Exception:
                                pass
                        except Exception as e:
                            logger.error(f"GA parse error: {e}")
                await asyncio.sleep(0.2)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"GA subscribe error: {e}")
                await asyncio.sleep(5)

    def _update_hotspots_from_prediction(self, artifact_id: str, risk_zones: List[Dict]):
        """根据预测结果更新热点"""
        hotspots = []
        for i, zone in enumerate(risk_zones):
            center = zone.get("center", {"x": 0, "y": 0, "z": 0})
            hotspots.append(RustHotspot(
                hotspot_id=f"{artifact_id}_HS{i:02d}",
                x=float(center.get("x", 0)),
                y=float(center.get("y", 0)),
                z=float(center.get("z", 0)),
                severity=float(zone.get("severity", 0.5)),
                area_cm2=float(zone.get("radius", 0.05)) * 100,
                required_coverage=float(zone.get("required_coverage", 0.95)),
            ))
        if hotspots:
            self._hotspot_cache[artifact_id] = hotspots

    async def _periodic_planning_loop(self):
        """每6小时批量规划"""
        while self._running:
            try:
                await self._plan_all_artifacts()
                self._stats["last_run"] = datetime.now().isoformat()
                logger.info(f"GA periodic planning complete: {self._stats['total_plans']} plans, avg_cov={self._stats['avg_coverage']:.3f}")
            except Exception as e:
                logger.error(f"GA periodic planning error: {e}")
            for _ in range(self._recalc_interval):
                if not self._running:
                    break
                await asyncio.sleep(1)

    async def _plan_all_artifacts(self):
        """批量规划所有器物"""
        total_cov = 0.0
        total_time = 0
        count = 0
        for aid, hotspots in self._hotspot_cache.items():
            if not hotspots:
                continue
            plan = self.plan_sync(
                artifact_id=aid,
                hotspots=hotspots,
                artifact_size=self._artifact_sizes.get(aid, {"width": 0.5, "height": 0.6, "depth": 0.4}),
            )
            if plan:
                total_cov += plan.estimated_weighted_coverage
                total_time += plan.planning_time_ms
                count += 1
                await self._push_plan_ws(aid, plan)
        if count:
            self._stats["total_plans"] += count
            self._stats["avg_coverage"] = round(total_cov / count, 4)
            self._stats["avg_planning_time_ms"] = int(total_time / count)

    async def _push_plan_ws(self, artifact_id: str, plan: SprayPathPlan):
        """通过WebSocket推送规划结果"""
        if not self.stream_mgr:
            return
        try:
            alert_stream = settings.REDIS_STREAMS.get("alerts", "stream:alerts")
            await self.stream_mgr.ensure_stream(alert_stream)
            payload = waypoints_to_dict(plan)
            await self.stream_mgr.publish(alert_stream, {
                "type": "spray_plan_update",
                "data": json.dumps({
                    "artifact_id": artifact_id,
                    "plan": payload,
                    "timestamp": datetime.now().isoformat(),
                }),
            })
        except Exception as e:
            logger.debug(f"WS push skipped: {e}")

    def plan_sync(
        self,
        artifact_id: str,
        hotspots: Optional[List[RustHotspot]] = None,
        artifact_size: Optional[Dict[str, float]] = None,
        population_size: int = 50,
        generations: int = 60,
    ) -> Optional[SprayPathPlan]:
        """同步规划接口"""
        self._init_components()
        if not self.planner:
            return None

        hs = hotspots or self._hotspot_cache.get(artifact_id, [])
        size = artifact_size or self._artifact_sizes.get(artifact_id, {"width": 0.5, "height": 0.6, "depth": 0.4})

        if not hs:
            hs = [
                RustHotspot(
                    hotspot_id=f"{artifact_id}_HS00",
                    x=0.0, y=0.0, z=0.05,
                    severity=0.5, area_cm2=10.0,
                    required_coverage=0.95,
                )
            ]

        plan = self.planner.optimize(
            artifact_id=artifact_id,
            hotspots=hs,
            artifact_size=size,
            population_size=population_size,
            generations=generations,
        )

        self._plans_cache[artifact_id] = waypoints_to_dict(plan)
        return plan

    def get_plan(self, artifact_id: str) -> Optional[Dict]:
        """获取缓存的规划结果"""
        return self._plans_cache.get(artifact_id)

    def get_all_plans(self) -> List[Dict]:
        """获取所有规划结果"""
        return list(self._plans_cache.values())

    def get_stats(self) -> Dict:
        return dict(self._stats)

    def stop(self):
        self._running = False
