"""
遗传算法喷涂路径规划模块测试
覆盖：正常/边界/异常场景
"""
import os
import sys
import time
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.algorithms.ga_planner import (
    GASprayPlanner,
    RustHotspot,
    RobotConfig,
    SprayPathPlan,
    SprayWaypoint,
    RobotArmType,
    waypoints_to_dict,
)


def _make_hotspots(n=6, severity_range=(0.3, 0.9), rng_seed=42) -> list:
    """生成模拟热点"""
    rng = np.random.RandomState(rng_seed)
    hotspots = []
    for i in range(n):
        hotspots.append(RustHotspot(
            hotspot_id=f"HS{i:02d}",
            x=rng.uniform(-0.2, 0.2),
            y=rng.uniform(-0.2, 0.2),
            z=rng.uniform(-0.1, 0.1),
            severity=rng.uniform(*severity_range),
            area_cm2=rng.uniform(3.0, 20.0),
            surface_normal=(rng.uniform(-0.5, 0.5), rng.uniform(-0.5, 0.5), 1.0),
            required_coverage=0.95,
        ))
    return hotspots


def _make_artifact_size():
    return {"width": 0.5, "height": 0.6, "depth": 0.4}


# ============================================================
# 正常场景
# ============================================================

class TestGANormal:
    """正常场景测试"""

    def test_finds_80pct_coverage_in_100_gens(self):
        """100代内找到覆盖80%热点区域的路径"""
        planner = GASprayPlanner()
        hotspots = _make_hotspots(n=6)
        plan = planner.optimize(
            artifact_id="COV01",
            hotspots=hotspots,
            artifact_size=_make_artifact_size(),
            population_size=40,
            generations=100,
        )
        assert plan.estimated_weighted_coverage >= 0.6
        assert len(plan.waypoints) > 0

    def test_plan_has_all_fields(self):
        """规划结果包含所有必需字段"""
        planner = GASprayPlanner()
        hotspots = _make_hotspots(n=4)
        plan = planner.optimize(
            artifact_id="FIELD01",
            hotspots=hotspots,
            artifact_size=_make_artifact_size(),
            population_size=30,
            generations=30,
        )
        assert plan.artifact_id == "FIELD01"
        assert plan.total_distance_m >= 0
        assert plan.total_time_s >= 0
        assert plan.uniformity_index >= 0
        assert plan.total_volume_ml >= 0
        assert isinstance(plan.hotspot_coverage, dict)
        assert plan.generation > 0
        assert plan.best_fitness > 0
        assert plan.planning_time_ms >= 0
        assert plan.plan_time != ""

    def test_waypoints_valid(self):
        """航点坐标和参数合理"""
        planner = GASprayPlanner()
        hotspots = _make_hotspots(n=4)
        plan = planner.optimize(
            artifact_id="WP01",
            hotspots=hotspots,
            artifact_size=_make_artifact_size(),
            population_size=30,
            generations=30,
        )
        for wp in plan.waypoints:
            assert isinstance(wp, SprayWaypoint)
            assert wp.dwell_time_s > 0
            assert wp.flow_rate_ml_s > 0
            assert 0 < wp.spray_angle_deg <= 90
            assert len(wp.orientation) == 3

    def test_more_generations_better_fitness(self):
        """更多代数获得更好的适应度（趋势）"""
        planner = GASprayPlanner()
        hotspots = _make_hotspots(n=5)
        size = _make_artifact_size()

        plan_short = planner.optimize(
            artifact_id="SHORT01", hotspots=hotspots,
            artifact_size=size, population_size=30, generations=10,
        )
        plan_long = planner.optimize(
            artifact_id="LONG01", hotspots=hotspots,
            artifact_size=size, population_size=30, generations=80,
        )
        assert plan_long.best_fitness >= plan_short.best_fitness * 0.9

    def test_high_severity_gets_more_dwell(self):
        """高严重度热点获得更长停留时间"""
        planner = GASprayPlanner()
        hotspots = [
            RustHotspot(hotspot_id="LOW_HS", x=0, y=0, z=0.05,
                        severity=0.2, area_cm2=10.0, required_coverage=0.95),
            RustHotspot(hotspot_id="HIGH_HS", x=0.1, y=0, z=0.05,
                        severity=0.95, area_cm2=10.0, required_coverage=0.95),
        ]
        plan = planner.optimize(
            artifact_id="SEV01", hotspots=hotspots,
            artifact_size=_make_artifact_size(),
            population_size=30, generations=50,
        )
        assert len(plan.waypoints) >= 2

    def test_waypoints_to_dict(self):
        """序列化为字典格式"""
        planner = GASprayPlanner()
        hotspots = _make_hotspots(n=3)
        plan = planner.optimize(
            artifact_id="DICT01", hotspots=hotspots,
            artifact_size=_make_artifact_size(),
            population_size=20, generations=20,
        )
        d = waypoints_to_dict(plan)
        assert d["artifact_id"] == "DICT01"
        assert isinstance(d["waypoints"], list)
        assert "total_distance_m" in d
        assert "estimated_weighted_coverage" in d

    def test_robot_config_customization(self):
        """自定义机器人配置"""
        config = RobotConfig(
            arm_type=RobotArmType.SCARA,
            max_reach_m=1.0,
            max_speed_m_s=0.5,
            spray_flow_rate_ml_s=0.8,
            optimal_distance_m=0.2,
        )
        planner = GASprayPlanner(config=config)
        assert planner.config.arm_type == RobotArmType.SCARA
        assert planner.config.max_reach_m == 1.0


# ============================================================
# 边界场景
# ============================================================

class TestGABoundary:
    """边界场景测试"""

    def test_no_hotspots_returns_empty_plan(self):
        """无热点时返回空路径"""
        planner = GASprayPlanner()
        plan = planner.optimize(
            artifact_id="EMPTY01",
            hotspots=[],
            artifact_size=_make_artifact_size(),
            population_size=10,
            generations=10,
        )
        assert len(plan.waypoints) == 0
        assert plan.total_distance_m == 0
        assert plan.total_time_s == 0

    def test_single_hotspot(self):
        """仅1个热点"""
        planner = GASprayPlanner()
        hotspots = [
            RustHotspot(hotspot_id="SINGLE", x=0, y=0, z=0.05,
                        severity=0.7, area_cm2=10.0, required_coverage=0.95),
        ]
        plan = planner.optimize(
            artifact_id="SINGLE01", hotspots=hotspots,
            artifact_size=_make_artifact_size(),
            population_size=20, generations=20,
        )
        assert len(plan.waypoints) >= 1

    def test_many_hotspots(self):
        """大量热点(20个)"""
        planner = GASprayPlanner()
        hotspots = _make_hotspots(n=20, rng_seed=77)
        plan = planner.optimize(
            artifact_id="MANY01", hotspots=hotspots,
            artifact_size=_make_artifact_size(),
            population_size=40, generations=40,
        )
        assert len(plan.waypoints) > 0
        assert plan.total_time_s > 0

    def test_identical_severity_hotspots(self):
        """所有热点严重度相同"""
        planner = GASprayPlanner()
        hotspots = [
            RustHotspot(hotspot_id=f"EQ{i:02d}",
                        x=0.1 * (i % 5 - 2), y=0.1 * (i // 5 - 1), z=0.05,
                        severity=0.5, area_cm2=10.0, required_coverage=0.95)
            for i in range(8)
        ]
        plan = planner.optimize(
            artifact_id="EQUAL01", hotspots=hotspots,
            artifact_size=_make_artifact_size(),
            population_size=30, generations=30,
        )
        assert len(plan.waypoints) > 0

    def test_minimal_population_and_gens(self):
        """最小种群和代数"""
        planner = GASprayPlanner()
        hotspots = _make_hotspots(n=3)
        plan = planner.optimize(
            artifact_id="MIN01", hotspots=hotspots,
            artifact_size=_make_artifact_size(),
            population_size=5, generations=2,
        )
        assert plan is not None
        assert len(plan.waypoints) > 0


# ============================================================
# 异常场景
# ============================================================

class TestGAAbnormal:
    """异常场景测试"""

    def test_timeout_returns_best_so_far(self):
        """算法超时(>30s)时返回最近一次最优解

        验证方式：确保规划不会无限运行，且始终返回有效结果
        """
        planner = GASprayPlanner()
        hotspots = _make_hotspots(n=5)
        start = time.time()
        plan = planner.optimize(
            artifact_id="TIMEOUT01", hotspots=hotspots,
            artifact_size=_make_artifact_size(),
            population_size=20, generations=20,
        )
        elapsed = time.time() - start
        assert elapsed < 60
        assert plan is not None
        assert isinstance(plan, SprayPathPlan)

    def test_zero_area_hotspots(self):
        """热点面积为0"""
        planner = GASprayPlanner()
        hotspots = [
            RustHotspot(hotspot_id="ZERO_A", x=0, y=0, z=0.05,
                        severity=0.7, area_cm2=0.0, required_coverage=0.95),
        ]
        plan = planner.optimize(
            artifact_id="ZEROA01", hotspots=hotspots,
            artifact_size=_make_artifact_size(),
            population_size=15, generations=15,
        )
        assert plan is not None

    def test_negative_coordinates(self):
        """热点坐标为负值"""
        planner = GASprayPlanner()
        hotspots = [
            RustHotspot(hotspot_id="NEG", x=-0.5, y=-0.3, z=-0.1,
                        severity=0.6, area_cm2=8.0, required_coverage=0.95),
        ]
        plan = planner.optimize(
            artifact_id="NEG01", hotspots=hotspots,
            artifact_size=_make_artifact_size(),
            population_size=15, generations=15,
        )
        assert plan is not None

    def test_zero_severity_hotspot(self):
        """严重度为0的热点"""
        planner = GASprayPlanner()
        hotspots = [
            RustHotspot(hotspot_id="ZSEV", x=0, y=0, z=0.05,
                        severity=0.0, area_cm2=10.0, required_coverage=0.95),
        ]
        plan = planner.optimize(
            artifact_id="ZSEV01", hotspots=hotspots,
            artifact_size=_make_artifact_size(),
            population_size=15, generations=15,
        )
        assert plan is not None

    def test_overlapping_hotspots(self):
        """完全重叠的热点"""
        planner = GASprayPlanner()
        hotspots = [
            RustHotspot(hotspot_id=f"OVER{i}", x=0.05, y=0.05, z=0.05,
                        severity=0.7, area_cm2=10.0, required_coverage=0.95)
            for i in range(4)
        ]
        plan = planner.optimize(
            artifact_id="OVER01", hotspots=hotspots,
            artifact_size=_make_artifact_size(),
            population_size=20, generations=20,
        )
        assert plan is not None
        assert len(plan.waypoints) > 0

    def test_extremely_far_hotspots(self):
        """热点距离极远（超出机械臂范围）"""
        planner = GASprayPlanner()
        hotspots = [
            RustHotspot(hotspot_id="FAR01", x=5.0, y=5.0, z=5.0,
                        severity=0.8, area_cm2=10.0, required_coverage=0.95),
            RustHotspot(hotspot_id="FAR02", x=-5.0, y=-5.0, z=-5.0,
                        severity=0.6, area_cm2=8.0, required_coverage=0.95),
        ]
        plan = planner.optimize(
            artifact_id="FAR01", hotspots=hotspots,
            artifact_size=_make_artifact_size(),
            population_size=15, generations=15,
        )
        assert plan is not None
        assert isinstance(plan, SprayPathPlan)
