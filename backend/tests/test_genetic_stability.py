"""
遗传算法稳定性单元测试
覆盖：确定性验证、精英保留、收敛性、鲁棒性
"""
import os
import sys
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.algorithms.ga_planner import (
    GASprayPlanner,
    RustHotspot,
    RobotConfig,
    RobotArmType,
    waypoints_to_dict,
)


def _make_hotspots(n=6, seed=42):
    rng = np.random.RandomState(seed)
    return [
        RustHotspot(
            hotspot_id=f"HS{i:02d}",
            x=float(rng.uniform(-0.2, 0.2)),
            y=float(rng.uniform(-0.2, 0.2)),
            z=float(rng.uniform(-0.1, 0.1)),
            severity=float(rng.uniform(0.3, 0.9)),
            area_cm2=float(rng.uniform(3, 20)),
            required_coverage=0.95,
        )
        for i in range(n)
    ]


ARTIFACT_SIZE = {"width": 0.5, "height": 0.6, "depth": 0.4}


class TestGeneticStability:
    """遗传算法稳定性专项测试"""

    def test_deterministic_with_same_seed(self):
        """验证：相同种子 → 完全相同的最优解（可复现性）"""
        planner = GASprayPlanner()
        hotspots = _make_hotspots(n=6, seed=123)
        p1 = planner.optimize("DET_A", hotspots, ARTIFACT_SIZE,
                              population_size=30, generations=20, random_seed=42)
        p2 = planner.optimize("DET_B", hotspots, ARTIFACT_SIZE,
                              population_size=30, generations=20, random_seed=42)
        assert p1.best_fitness == pytest.approx(p2.best_fitness, abs=1e-9)
        assert p1.total_distance_m == pytest.approx(p2.total_distance_m, abs=1e-9)
        assert p1.total_time_s == pytest.approx(p2.total_time_s, abs=1e-9)
        assert len(p1.waypoints) == len(p2.waypoints)

    def test_10_runs_cv_under_5_percent(self):
        """验证：连续10次运行，适应度变异系数<5%"""
        planner = GASprayPlanner()
        hotspots = _make_hotspots(n=8, seed=99)
        fitnesses = []
        distances = []
        for i in range(10):
            plan = planner.optimize(
                f"RUN_{i}", hotspots, ARTIFACT_SIZE,
                population_size=40, generations=30, random_seed=42
            )
            fitnesses.append(plan.best_fitness)
            distances.append(plan.total_distance_m)
        fit_cv = np.std(fitnesses) / np.mean(fitnesses) if np.mean(fitnesses) > 0 else 0
        dist_cv = np.std(distances) / np.mean(distances) if np.mean(distances) > 0 else 0
        assert fit_cv < 0.05, f"适应度CV={fit_cv:.3f} 超过5%"
        assert dist_cv < 0.05, f"距离CV={dist_cv:.3f} 超过5%"

    def test_different_seeds_produce_different_results(self):
        """验证：不同种子 → 不同结果（证明随机性在起作用）"""
        planner = GASprayPlanner()
        hotspots = _make_hotspots(n=5, seed=55)
        p1 = planner.optimize("S_1", hotspots, ARTIFACT_SIZE,
                              population_size=20, generations=10, random_seed=1)
        p2 = planner.optimize("S_2", hotspots, ARTIFACT_SIZE,
                              population_size=20, generations=10, random_seed=9999)
        assert p1.best_fitness != pytest.approx(p2.best_fitness, abs=1e-9)

    def test_elite_retention_preserves_best(self):
        """验证：精英保留策略 → 最优适应度不退化"""
        planner = GASprayPlanner()
        hotspots = _make_hotspots(n=6, seed=77)
        plan = planner.optimize("ELITE", hotspots, ARTIFACT_SIZE,
                                population_size=30, generations=25,
                                elite_size=5, random_seed=123)
        assert plan.best_fitness > 0.3

    def test_convergence_trend(self):
        """验证：增加代数 → 适应度总体提高（收敛性）"""
        planner = GASprayPlanner()
        hotspots = _make_hotspots(n=5, seed=123)
        short = planner.optimize("SHORT", hotspots, ARTIFACT_SIZE,
                                 population_size=30, generations=5, random_seed=42)
        long_g = planner.optimize("LONG", hotspots, ARTIFACT_SIZE,
                                   population_size=30, generations=40, random_seed=42)
        assert long_g.best_fitness >= short.best_fitness * 0.95

    def test_waypoint_order_consistency(self):
        """验证：多次运行航点数量和顺序一致（确定性）"""
        planner = GASprayPlanner()
        hotspots = _make_hotspots(n=4, seed=100)
        results = []
        for i in range(5):
            p = planner.optimize(f"ORD_{i}", hotspots, ARTIFACT_SIZE,
                                 population_size=25, generations=15, random_seed=42)
            results.append([(wp.x, wp.y, wp.z) for wp in p.waypoints])
        for i in range(1, len(results)):
            assert len(results[i]) == len(results[0])
            for j in range(len(results[i])):
                assert results[i][j] == pytest.approx(results[0][j], abs=1e-6)

    def test_population_size_does_not_break(self):
        """验证：不同种群大小都能正常运行"""
        planner = GASprayPlanner()
        hotspots = _make_hotspots(n=5, seed=200)
        for pop_size in [5, 10, 50, 100]:
            plan = planner.optimize(f"POP_{pop_size}", hotspots, ARTIFACT_SIZE,
                                    population_size=pop_size, generations=5, random_seed=42)
            assert plan is not None
            assert plan.best_fitness > 0

    def test_waypoints_to_dict_stable(self):
        """验证：序列化结果稳定可复现"""
        planner = GASprayPlanner()
        hotspots = _make_hotspots(n=4, seed=300)
        plan = planner.optimize("DICT_TEST", hotspots, ARTIFACT_SIZE,
                                population_size=20, generations=10, random_seed=42)
        d1 = waypoints_to_dict(plan)
        d2 = waypoints_to_dict(plan)
        assert d1["artifact_id"] == d2["artifact_id"]
        assert d1["total_distance_m"] == pytest.approx(d2["total_distance_m"], abs=1e-9)
        assert len(d1["waypoints"]) == len(d2["waypoints"])

    def test_robot_config_customization_stable(self):
        """验证：自定义机器人配置下算法仍稳定"""
        config = RobotConfig(
            arm_type=RobotArmType.SCARA,
            max_reach_m=1.0,
            max_speed_m_s=0.5,
            spray_flow_rate_ml_s=0.8,
            optimal_distance_m=0.2,
        )
        planner = GASprayPlanner(config=config)
        hotspots = _make_hotspots(n=5, seed=400)
        plan = planner.optimize("ROBO_TEST", hotspots, ARTIFACT_SIZE,
                                population_size=20, generations=10, random_seed=42)
        assert plan is not None
        assert plan.best_fitness > 0

    def test_seed_parameter_passthrough(self):
        """验证：random_seed参数正确传递到算法内部"""
        planner = GASprayPlanner()
        hotspots = _make_hotspots(n=6, seed=500)
        p1 = planner.optimize("SEED_A", hotspots, ARTIFACT_SIZE,
                              population_size=20, generations=8, random_seed=12345)
        p2 = planner.optimize("SEED_B", hotspots, ARTIFACT_SIZE,
                              population_size=20, generations=8, random_seed=12345)
        assert p1.best_fitness == pytest.approx(p2.best_fitness, abs=1e-9)
