"""
文物脆弱性综合评分(AHP)模块测试
覆盖：正常/边界/异常场景
"""
import os
import sys
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.algorithms.ahp_scorer import (
    AHPScorer,
    ArtifactVulnerabilityData,
    VulnerabilityScore,
    VulnerabilityLevel,
    LEVEL_COLORS,
    LEVEL_NAMES,
    DEFAULT_AHP_MATRICES,
    get_level_info,
)


def _make_high_risk_data(aid="HIGH01") -> ArtifactVulnerabilityData:
    """高风险+低稳定性数据"""
    return ArtifactVulnerabilityData(
        artifact_id=aid,
        eruption_probability=0.85,
        risk_level=4,
        chloride_concentration=8.5,
        wall_thickness_uniformity=0.4,
        crack_index=0.8,
        deformation_degree=0.6,
        repair_count=6,
        last_repair_years_ago=30.0,
        hall_x=5.0,
        hall_y=3.0,
    )


def _make_low_risk_data(aid="LOW01") -> ArtifactVulnerabilityData:
    """低风险+高稳定性数据"""
    return ArtifactVulnerabilityData(
        artifact_id=aid,
        eruption_probability=0.05,
        risk_level=1,
        chloride_concentration=0.5,
        wall_thickness_uniformity=0.95,
        crack_index=0.05,
        deformation_degree=0.02,
        repair_count=0,
        last_repair_years_ago=2.0,
        hall_x=1.0,
        hall_y=1.0,
    )


# ============================================================
# 正常场景
# ============================================================

class TestAHPNormal:
    """正常场景测试"""

    def test_high_risk_high_score(self):
        """高风险锈蚀+低稳定性得分>75"""
        scorer = AHPScorer()
        result = scorer.score(_make_high_risk_data())
        assert result.total_score > 75
        assert result.level in (VulnerabilityLevel.POOR, VulnerabilityLevel.DANGEROUS)

    def test_low_risk_low_score(self):
        """低风险+高稳定性得分<40"""
        scorer = AHPScorer()
        result = scorer.score(_make_low_risk_data())
        assert result.total_score < 40
        assert result.level in (VulnerabilityLevel.EXCELLENT, VulnerabilityLevel.GOOD)

    def test_high_risk_higher_than_low(self):
        """高风险得分 > 低风险得分"""
        scorer = AHPScorer()
        high = scorer.score(_make_high_risk_data())
        low = scorer.score(_make_low_risk_data())
        assert high.total_score > low.total_score

    def test_score_range_0_100(self):
        """评分范围在0-100"""
        scorer = AHPScorer()
        rng = np.random.RandomState(42)
        for _ in range(50):
            data = ArtifactVulnerabilityData(
                artifact_id=f"RND_{_}",
                eruption_probability=rng.uniform(0, 1),
                risk_level=rng.randint(1, 5),
                chloride_concentration=rng.uniform(0, 10),
                wall_thickness_uniformity=rng.uniform(0.5, 1.0),
                crack_index=rng.uniform(0, 1),
                deformation_degree=rng.uniform(0, 0.5),
                repair_count=rng.randint(0, 8),
                last_repair_years_ago=rng.uniform(0.5, 40),
            )
            result = scorer.score(data)
            assert 0 <= result.total_score <= 100

    def test_sub_scores_present(self):
        """包含三个子维度得分"""
        scorer = AHPScorer()
        result = scorer.score(_make_high_risk_data())
        assert "rust_risk" in result.sub_scores
        assert "structural_stability" in result.sub_scores
        assert "repair_history" in result.sub_scores

    def test_criterion_contributions_sum_near_100(self):
        """各维度贡献占比之和接近100%"""
        scorer = AHPScorer()
        result = scorer.score(_make_high_risk_data())
        total = sum(result.criterion_contributions.values())
        assert abs(total - 100) < 15

    def test_level_classification(self):
        """等级分类正确"""
        scorer = AHPScorer()
        for lvl, (lo, hi) in {
            VulnerabilityLevel.EXCELLENT: (0, 20),
            VulnerabilityLevel.GOOD: (20, 40),
            VulnerabilityLevel.MODERATE: (40, 60),
            VulnerabilityLevel.POOR: (60, 80),
            VulnerabilityLevel.DANGEROUS: (80, 101),
        }.items():
            assert scorer._classify_level((lo + hi) / 2) == lvl

    def test_batch_score(self):
        """批量评分"""
        scorer = AHPScorer()
        data_list = [_make_high_risk_data(f"H{i:02d}") for i in range(5)] + \
                    [_make_low_risk_data(f"L{i:02d}") for i in range(5)]
        results = scorer.batch_score(data_list)
        assert len(results) == 10
        high_scores = [r.total_score for r in results[:5]]
        low_scores = [r.total_score for r in results[5:]]
        assert np.mean(high_scores) > np.mean(low_scores)

    def test_recommendations_for_high_risk(self):
        """高风险产生保护建议"""
        scorer = AHPScorer()
        result = scorer.score(_make_high_risk_data())
        assert len(result.recommendations) > 0

    def test_heatmap_export(self):
        """热力图数据导出格式正确"""
        scorer = AHPScorer()
        data_list = [_make_high_risk_data(f"H{i:02d}") for i in range(3)]
        scores = scorer.batch_score(data_list)
        heatmap = scorer.export_heatmap_data(scores)
        assert len(heatmap) == 3
        for h in heatmap:
            assert "artifact_id" in h
            assert "x" in h
            assert "y" in h
            assert "value" in h
            assert "level" in h
            assert "color" in h

    def test_level_colors_and_names_complete(self):
        """每个等级都有颜色和中文名"""
        for lvl in VulnerabilityLevel:
            assert lvl in LEVEL_COLORS
            assert lvl in LEVEL_NAMES
            assert LEVEL_COLORS[lvl].startswith("#")
            assert len(LEVEL_NAMES[lvl]) > 0

    def test_get_level_info(self):
        """get_level_info辅助函数"""
        for score in [10, 30, 50, 70, 90]:
            val, color, name = get_level_info(score)
            assert val in [e.value for e in VulnerabilityLevel]
            assert color.startswith("#")
            assert len(name) > 0


# ============================================================
# 边界场景
# ============================================================

class TestAHPBoundary:
    """边界场景测试"""

    def test_missing_indicator_uses_default(self):
        """某项指标缺失时使用默认中值"""
        scorer = AHPScorer()
        data = ArtifactVulnerabilityData(
            artifact_id="MISS01",
            eruption_probability=0.5,
            risk_level=2,
            chloride_concentration=3.0,
            wall_thickness_uniformity=0.9,
            crack_index=0.1,
            deformation_degree=0.05,
            repair_count=1,
            last_repair_years_ago=10.0,
        )
        result = scorer.score(data)
        assert result.total_score > 0
        assert 0 <= result.total_score <= 100

    def test_all_zero_risk(self):
        """所有风险指标为零"""
        scorer = AHPScorer()
        data = ArtifactVulnerabilityData(
            artifact_id="ZERO01",
            eruption_probability=0.0,
            risk_level=1,
            chloride_concentration=0.0,
            wall_thickness_uniformity=1.0,
            crack_index=0.0,
            deformation_degree=0.0,
            repair_count=0,
            last_repair_years_ago=0.5,
        )
        result = scorer.score(data)
        assert result.total_score < 30

    def test_extreme_high_risk(self):
        """极端高风险所有指标"""
        scorer = AHPScorer()
        data = ArtifactVulnerabilityData(
            artifact_id="EXTREME01",
            eruption_probability=1.0,
            risk_level=4,
            chloride_concentration=15.0,
            wall_thickness_uniformity=0.0,
            crack_index=1.0,
            deformation_degree=1.0,
            repair_count=10,
            last_repair_years_ago=50.0,
        )
        result = scorer.score(data)
        assert result.total_score >= 60

    def test_consistency_ratio_within_limit(self):
        """默认判断矩阵CR<0.1"""
        scorer = AHPScorer()
        assert scorer.consistency_ratio < 0.1


# ============================================================
# 异常场景
# ============================================================

class TestAHPAbnormal:
    """异常场景测试"""

    def test_unnormalized_weight_matrix_auto_normalize(self):
        """权重矩阵未归一化时自动归一化"""
        bad_matrices = {
            "criteria": np.array([
                [1.0, 6.0, 10.0],
                [0.167, 1.0, 5.0],
                [0.1, 0.2, 1.0],
            ]),
            "rust_sub": DEFAULT_AHP_MATRICES["rust_sub"].copy(),
            "struct_sub": DEFAULT_AHP_MATRICES["struct_sub"].copy(),
            "repair_sub": DEFAULT_AHP_MATRICES["repair_sub"].copy(),
        }
        scorer = AHPScorer(config_matrices=bad_matrices)
        result = scorer.score(_make_high_risk_data("UNNORM01"))
        assert 0 <= result.total_score <= 100

    def test_invalid_matrix_shape_fallback(self):
        """无效矩阵形状时回退到默认"""
        bad_matrices = {
            "criteria": np.array([[1.0]]),
            "rust_sub": "not_a_matrix",
            "struct_sub": None,
            "repair_sub": DEFAULT_AHP_MATRICES["repair_sub"].copy(),
        }
        scorer = AHPScorer(config_matrices=bad_matrices)
        result = scorer.score(_make_high_risk_data("BADSHAPE01"))
        assert result is not None
        assert 0 <= result.total_score <= 100

    def test_none_config_uses_defaults(self):
        """配置为None时使用默认矩阵"""
        scorer = AHPScorer(config_matrices=None)
        result = scorer.score(_make_high_risk_data())
        assert result.total_score > 0

    def test_singular_matrix_handled(self):
        """近似奇异矩阵不崩溃"""
        near_singular = {
            "criteria": np.array([
                [1.0, 1.0, 1.0],
                [1.0, 1.0, 1.0],
                [1.0, 1.0, 1.0],
            ]),
            "rust_sub": DEFAULT_AHP_MATRICES["rust_sub"].copy(),
            "struct_sub": DEFAULT_AHP_MATRICES["struct_sub"].copy(),
            "repair_sub": DEFAULT_AHP_MATRICES["repair_sub"].copy(),
        }
        scorer = AHPScorer(config_matrices=near_singular)
        result = scorer.score(_make_high_risk_data("SING01"))
        assert result is not None
