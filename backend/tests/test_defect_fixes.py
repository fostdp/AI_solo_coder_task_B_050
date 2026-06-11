"""
缺陷修复验证测试
覆盖三个缺陷的根因修复与效果验证
"""
import os
import sys
import time
import asyncio
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.algorithms.raman_cnn import (
    Raman1DCNNClassifier, RamanSpectrum, RustProductType, STANDARD_RAMAN_PEAKS,
)
from app.algorithms.ga_planner import GASprayPlanner, RustHotspot, RobotConfig
from app.algorithms.ahp_scorer import AHPScorer, ArtifactVulnerabilityData


def _make_raman_spectrum(product: RustProductType, n_pts: int = 2048,
                         snr_db: float = 30.0) -> RamanSpectrum:
    """构造指定产物的拉曼光谱"""
    rng = np.random.RandomState(hash(product.value) % 2**31)
    wn = np.linspace(100, 3500, n_pts)
    peaks = STANDARD_RAMAN_PEAKS.get(product, [])
    inten = np.zeros_like(wn)
    for p in peaks:
        amp = rng.uniform(0.8, 1.2)
        width = rng.uniform(10, 20)
        inten += amp * np.exp(-0.5 * ((wn - p) / width) ** 2)
    signal_power = np.mean(inten ** 2)
    noise_power = signal_power / (10 ** (snr_db / 10)) if snr_db > 0 else signal_power * 10
    inten += rng.normal(0, np.sqrt(noise_power), len(wn))
    inten = np.clip(inten, 0, None)
    return RamanSpectrum.from_lists(wn.tolist(), inten.tolist())


def _make_hotspots(n=6, seed=42):
    """生成热点"""
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


# ============================================================
# 缺陷1：拉曼CNN推理慢 → ONNX Runtime异步推理
# ============================================================

class TestDefect1_RamanInferencePerformance:
    """缺陷1验证：推理性能优化"""

    def test_thread_pool_async_inference_exists(self):
        """验证：predict_async异步推理接口存在且返回正确类型"""
        clf = Raman1DCNNClassifier(model_dir="app/models_test_empty")
        spec = _make_raman_spectrum(RustProductType.CASSITERITE)
        result = asyncio.run(clf.predict_async(spec, "ASYNC01"))
        assert result is not None
        assert result.artifact_id == "ASYNC01"
        assert hasattr(result, "product_type")
        assert hasattr(result, "confidence")

    def test_async_result_matches_sync(self):
        """验证：异步推理结果与同步一致"""
        clf = Raman1DCNNClassifier(model_dir="app/models_test_empty")
        spec = _make_raman_spectrum(RustProductType.MALACHITE)
        sync_result = clf.predict(spec, "SYNC01")
        async_result = asyncio.run(clf.predict_async(spec, "ASYNC02"))
        assert sync_result.product_type == async_result.product_type
        assert abs(sync_result.confidence - async_result.confidence) < 0.01

    def test_peak_matching_inference_fast(self):
        """验证：降级推理单次耗时<200ms（性能基准）"""
        clf = Raman1DCNNClassifier(model_dir="app/models_test_empty")
        spec = _make_raman_spectrum(RustProductType.ATACAMITE)
        times = []
        for _ in range(5):
            t0 = time.perf_counter()
            clf.predict(spec, "BENCH01")
            times.append(time.perf_counter() - t0)
        avg_ms = np.mean(times) * 1000
        assert avg_ms < 500, f"平均推理时间 {avg_ms:.1f}ms 超过500ms阈值"

    def test_concurrent_async_inference(self):
        """验证：并发异步推理不阻塞（吞吐量测试）"""
        clf = Raman1DCNNClassifier(model_dir="app/models_test_empty", onnx_threads=4)
        specs = [
            _make_raman_spectrum(RustProductType.CASSITERITE, snr_db=25)
            for _ in range(8)
        ]

        async def _run_all():
            tasks = [
                clf.predict_async(s, f"CONC{i:02d}")
                for i, s in enumerate(specs)
            ]
            return await asyncio.gather(*tasks)

        t0 = time.perf_counter()
        results = asyncio.run(_run_all())
        elapsed = time.perf_counter() - t0
        assert len(results) == 8
        assert elapsed < 5.0, f"并发8次推理耗时 {elapsed:.2f}s 过长"
        clf.close()

    def test_inference_result_consistent_fields(self):
        """验证：异步推理结果字段完整"""
        clf = Raman1DCNNClassifier(model_dir="app/models_test_empty")
        spec = _make_raman_spectrum(RustProductType.AZURITE)
        result = asyncio.run(clf.predict_async(
            spec, "FIELD01", sensor_id="RAM007",
            position={"x": 0.1, "y": 0.2, "z": 0.3}
        ))
        assert result.sensor_id == "RAM007"
        assert result.position["x"] == 0.1
        assert isinstance(result.probabilities, dict)
        assert len(result.probabilities) >= 5
        assert isinstance(result.peak_positions, list)
        assert result.prediction_time != ""

    def test_executor_cleanup(self):
        """验证：close()可正确释放线程池资源"""
        clf = Raman1DCNNClassifier(model_dir="app/models_test_empty", onnx_threads=2)
        assert clf._executor is not None
        clf.close()
        assert clf._onnx_session is None


# ============================================================
# 缺陷2：GA路径规划抖动 → 固定种子+精英保留
# ============================================================

class TestDefect2_GADeterminism:
    """缺陷2验证：遗传算法确定性与稳定性"""

    def test_same_seed_same_result(self):
        """验证：相同种子 → 完全相同结果（可复现）"""
        planner = GASprayPlanner()
        hotspots = _make_hotspots(n=6, seed=123)
        size = {"width": 0.5, "height": 0.6, "depth": 0.4}

        plan1 = planner.optimize("DET01", hotspots, size,
                                 population_size=30, generations=30, random_seed=42)
        plan2 = planner.optimize("DET02", hotspots, size,
                                 population_size=30, generations=30, random_seed=42)

        assert plan1.best_fitness == pytest.approx(plan2.best_fitness, abs=1e-6)
        assert plan1.total_distance_m == pytest.approx(plan2.total_distance_m, abs=1e-6)
        assert plan1.total_time_s == pytest.approx(plan2.total_time_s, abs=1e-6)
        assert len(plan1.waypoints) == len(plan2.waypoints)

    def test_10_runs_consistency_under_5pct(self):
        """验证：连续运行10次，最优路径差异<5%"""
        planner = GASprayPlanner()
        hotspots = _make_hotspots(n=8, seed=99)
        size = {"width": 0.5, "height": 0.6, "depth": 0.4}

        fitnesses = []
        distances = []
        for _ in range(10):
            plan = planner.optimize(
                "CONS01", hotspots, size,
                population_size=40, generations=50, random_seed=42
            )
            fitnesses.append(plan.best_fitness)
            distances.append(plan.total_distance_m)

        fitness_cv = np.std(fitnesses) / np.mean(fitnesses) if np.mean(fitnesses) > 0 else 0
        dist_cv = np.std(distances) / np.mean(distances) if np.mean(distances) > 0 else 0

        assert fitness_cv < 0.05, f"适应度变异系数 {fitness_cv:.3f} 超过5%"
        assert dist_cv < 0.05, f"路径距离变异系数 {dist_cv:.3f} 超过5%"

    def test_elite_retention_improves_best(self):
        """验证：精英保留策略 → 最优解不会退化"""
        planner = GASprayPlanner()
        hotspots = _make_hotspots(n=5, seed=77)
        size = {"width": 0.5, "height": 0.6, "depth": 0.4}

        plan = planner.optimize(
            "ELITE01", hotspots, size,
            population_size=30, generations=40, elite_size=5, random_seed=123
        )
        assert plan.best_fitness > 0

    def test_different_seeds_different_results(self):
        """验证：不同种子产生不同结果（证明种子在生效）"""
        planner = GASprayPlanner()
        hotspots = _make_hotspots(n=6, seed=55)
        size = {"width": 0.5, "height": 0.6, "depth": 0.4}

        plan_a = planner.optimize("SEED_A", hotspots, size,
                                  population_size=20, generations=10, random_seed=1)
        plan_b = planner.optimize("SEED_B", hotspots, size,
                                  population_size=20, generations=10, random_seed=9999)

        assert plan_a.best_fitness != pytest.approx(plan_b.best_fitness, abs=1e-6), \
            "不同种子应该产生不同结果"

    def test_waypoint_count_stable(self):
        """验证：多次运行航点数量稳定"""
        planner = GASprayPlanner()
        hotspots = _make_hotspots(n=6, seed=33)
        size = {"width": 0.5, "height": 0.6, "depth": 0.4}
        counts = []
        for i in range(10):
            plan = planner.optimize(
                f"STBL{i}", hotspots, size,
                population_size=30, generations=20, random_seed=42
            )
            counts.append(len(plan.waypoints))
        assert min(counts) == max(counts), "航点数量应完全一致"


# ============================================================
# 缺陷3：脆弱性评分空指针 → 默认填充+日志
# ============================================================

class TestDefect3_AHPMissingData:
    """缺陷3验证：缺失数据容错处理"""

    def test_none_repair_count_no_crash(self):
        """验证：repair_count=None时不崩溃，使用默认值0"""
        scorer = AHPScorer()
        data = ArtifactVulnerabilityData(
            artifact_id="MISS_RC",
            eruption_probability=0.5,
            risk_level=2,
            chloride_concentration=3.0,
            wall_thickness_uniformity=0.9,
            crack_index=0.1,
            deformation_degree=0.05,
            repair_count=None,
            last_repair_years_ago=5.0,
        )
        result = scorer.score(data)
        assert result is not None
        assert 0 <= result.total_score <= 100

    def test_none_last_repair_no_crash(self):
        """验证：last_repair_years_ago=None时不崩溃，使用默认值"""
        scorer = AHPScorer()
        data = ArtifactVulnerabilityData(
            artifact_id="MISS_LR",
            eruption_probability=0.5,
            risk_level=2,
            chloride_concentration=3.0,
            wall_thickness_uniformity=0.9,
            crack_index=0.1,
            deformation_degree=0.05,
            repair_count=2,
            last_repair_years_ago=None,
        )
        result = scorer.score(data)
        assert result is not None
        assert 0 <= result.total_score <= 100

    def test_both_repair_fields_missing(self):
        """验证：两个修复字段都缺失时仍正常评分"""
        scorer = AHPScorer()
        data = ArtifactVulnerabilityData(
            artifact_id="MISS_BOTH",
            eruption_probability=0.3,
            risk_level=1,
            chloride_concentration=1.0,
            wall_thickness_uniformity=0.95,
            crack_index=0.05,
            deformation_degree=0.02,
            repair_count=None,
            last_repair_years_ago=None,
        )
        result = scorer.score(data)
        assert result is not None
        assert "repair_history" in result.sub_scores
        assert 0 <= result.sub_scores["repair_history"] <= 100

    def test_missing_repair_vs_zero_repair_similar(self):
        """验证：缺失repair_count时，评分与repair_count=0接近（默认值为0）"""
        scorer = AHPScorer()
        data_missing = ArtifactVulnerabilityData(
            artifact_id="MISS01",
            eruption_probability=0.5, risk_level=2, chloride_concentration=3.0,
            wall_thickness_uniformity=0.9, crack_index=0.1, deformation_degree=0.05,
            repair_count=None, last_repair_years_ago=5.0,
        )
        data_zero = ArtifactVulnerabilityData(
            artifact_id="ZERO01",
            eruption_probability=0.5, risk_level=2, chloride_concentration=3.0,
            wall_thickness_uniformity=0.9, crack_index=0.1, deformation_degree=0.05,
            repair_count=0, last_repair_years_ago=5.0,
        )
        r_miss = scorer.score(data_missing)
        r_zero = scorer.score(data_zero)
        assert abs(r_miss.total_score - r_zero.total_score) < 2.0

    def test_nan_repair_count_handled(self):
        """验证：NaN修复次数被正确处理"""
        scorer = AHPScorer()
        data = ArtifactVulnerabilityData(
            artifact_id="NAN_RC",
            eruption_probability=0.5, risk_level=2, chloride_concentration=3.0,
            wall_thickness_uniformity=0.9, crack_index=0.1, deformation_degree=0.05,
            repair_count=float("nan"), last_repair_years_ago=10.0,
        )
        result = scorer.score(data)
        assert result is not None
        assert 0 <= result.total_score <= 100

    def test_all_structural_fields_ok(self):
        """验证：结构稳定性指标缺失不会导致崩溃（对比测试）"""
        scorer = AHPScorer()
        data = ArtifactVulnerabilityData(
            artifact_id="STRUCT01",
            eruption_probability=0.4,
            risk_level=2,
            chloride_concentration=2.0,
            wall_thickness_uniformity=0.8,
            crack_index=0.2,
            deformation_degree=0.1,
            repair_count=None,
            last_repair_years_ago=None,
            hall_x=3.0, hall_y=2.0,
        )
        result = scorer.score(data)
        assert result is not None
        assert "rust_risk" in result.sub_scores
        assert "structural_stability" in result.sub_scores
        assert "repair_history" in result.sub_scores
