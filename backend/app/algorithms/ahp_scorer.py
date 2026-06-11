"""
文物脆弱性综合评分模块
基于层次分析法(AHP)融合多维指标，计算0-100的综合脆弱性指数

指标体系（三层结构）：
├── 一级指标
│   ├── C1 粉状锈风险 (权重可配置)
│   ├── C2 结构稳定性 (权重可配置)
│   └── C3 历史修复次数 (权重可配置)
├── 二级指标
│   ├── C1-1 爆发概率 (0-1)
│   ├── C1-2 风险等级 (1-4)
│   ├── C1-3 氯离子浓度 (μg/m³)
│   ├── C2-1 壁厚均匀度 (0-1，CT模拟)
│   ├── C2-2 裂隙指数 (0-1，CT模拟)
│   ├── C2-3 形变度 (0-1，CT模拟)
│   ├── C3-1 修复次数
│   └── C3-2 最后修复距今(年)

设计说明：
- 支持从配置文件加载判断矩阵
- 一致性比率(CR)自动校验，CR>0.1需调整矩阵
- 结果标准化到[0, 100]分
- 热力展示：0-20优(蓝) / 20-40良(绿) / 40-60中(黄) / 60-80差(橙) / 80-100危险(红)
"""

import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from enum import Enum
from datetime import datetime

import numpy as np

logger = logging.getLogger("ahp_scorer")


class VulnerabilityLevel(str, Enum):
    EXCELLENT = "excellent"    # 0-20
    GOOD = "good"              # 20-40
    MODERATE = "moderate"      # 40-60
    POOR = "poor"              # 60-80
    DANGEROUS = "dangerous"    # 80-100


LEVEL_COLORS = {
    VulnerabilityLevel.EXCELLENT: "#3B82F6",   # 蓝
    VulnerabilityLevel.GOOD: "#10B981",        # 绿
    VulnerabilityLevel.MODERATE: "#F59E0B",    # 黄
    VulnerabilityLevel.POOR: "#F97316",        # 橙
    VulnerabilityLevel.DANGEROUS: "#EF4444",   # 红
}


LEVEL_NAMES = {
    VulnerabilityLevel.EXCELLENT: "状态优秀",
    VulnerabilityLevel.GOOD: "状态良好",
    VulnerabilityLevel.MODERATE: "中度脆弱",
    VulnerabilityLevel.POOR: "高度脆弱",
    VulnerabilityLevel.DANGEROUS: "极度危险",
}


@dataclass
class CriterionWeights:
    rust_risk: float
    structural_stability: float
    repair_history: float

    rust_eruption_prob: float
    rust_risk_level: float
    rust_chloride: float

    struct_wall_uniformity: float
    struct_crack_index: float
    struct_deformation: float

    repair_count: float
    repair_years_since: float


@dataclass
class ArtifactVulnerabilityData:
    artifact_id: str
    eruption_probability: float = 0.0
    risk_level: int = 1
    chloride_concentration: float = 1.0
    wall_thickness_uniformity: float = 0.9
    crack_index: float = 0.1
    deformation_degree: float = 0.05
    repair_count: int = 0
    last_repair_years_ago: float = 10.0
    hall_x: float = 0.0
    hall_y: float = 0.0


@dataclass
class VulnerabilityScore:
    artifact_id: str
    total_score: float
    level: VulnerabilityLevel
    sub_scores: Dict[str, float]
    criterion_contributions: Dict[str, float]
    consistency_ratio: float
    hall_x: float
    hall_y: float
    calculation_time: str
    recommendations: List[str] = field(default_factory=list)


DEFAULT_AHP_MATRICES = {
    "criteria": np.array([
        [1.0, 3.0, 5.0],
        [1/3, 1.0, 3.0],
        [1/5, 1/3, 1.0],
    ]),
    "rust_sub": np.array([
        [1.0, 3.0, 2.0],
        [1/3, 1.0, 1/2],
        [1/2, 2.0, 1.0],
    ]),
    "struct_sub": np.array([
        [1.0, 5.0, 3.0],
        [1/5, 1.0, 1/3],
        [1/3, 3.0, 1.0],
    ]),
    "repair_sub": np.array([
        [1.0, 2.0],
        [1/2, 1.0],
    ]),
}


class AHPScorer:
    """层次分析法(AHP)脆弱性评分器"""

    RI_TABLE = [0.00, 0.00, 0.58, 0.90, 1.12, 1.24, 1.32, 1.41, 1.45, 1.49, 1.51]

    def __init__(self, config_matrices: Optional[Dict] = None):
        self.matrices = self._load_matrices(config_matrices)
        self.weights = self._compute_all_weights()
        self.consistency_ratio = 0.0
        self._validate_consistency()
        logger.info(f"AHP Scorer initialized, global CR={self.consistency_ratio:.4f}")

    def _load_matrices(self, config: Optional[Dict]) -> Dict[str, np.ndarray]:
        """从配置加载或使用默认判断矩阵"""
        if config is None:
            return {k: v.copy() for k, v in DEFAULT_AHP_MATRICES.items()}

        matrices = {}
        for key, default in DEFAULT_AHP_MATRICES.items():
            if key in config and config[key] is not None:
                try:
                    m = np.array(config[key], dtype=np.float64)
                    if m.shape == default.shape:
                        matrices[key] = m
                        continue
                except Exception as e:
                    logger.warning(f"Invalid AHP matrix '{key}': {e}, using default")
            matrices[key] = default.copy()
        return matrices

    def _compute_weights(self, matrix: np.ndarray) -> Tuple[np.ndarray, float]:
        """用特征向量法计算权重 + 一致性比率CR"""
        n = matrix.shape[0]
        eigvals, eigvecs = np.linalg.eig(matrix)
        max_idx = int(np.argmax(np.real(eigvals)))
        lambda_max = float(np.real(eigvals[max_idx]))
        w = np.real(eigvecs[:, max_idx])
        w = w / (w.sum() if abs(w.sum()) > 1e-10 else 1.0)
        w = np.abs(w)
        w = w / (w.sum() if abs(w.sum()) > 1e-10 else 1.0)

        if n > 2:
            CI = (lambda_max - n) / (n - 1)
            RI = self.RI_TABLE[n - 1] if n - 1 < len(self.RI_TABLE) else 1.51
            CR = CI / RI if RI > 1e-10 else 0.0
        else:
            CI = 0.0
            CR = 0.0

        return w, CR

    def _compute_all_weights(self) -> CriterionWeights:
        """计算所有层级的权重"""
        W_criteria, CR1 = self._compute_weights(self.matrices["criteria"])
        W_rust, CR2 = self._compute_weights(self.matrices["rust_sub"])
        W_struct, CR3 = self._compute_weights(self.matrices["struct_sub"])
        W_repair, CR4 = self._compute_weights(self.matrices["repair_sub"])

        self.consistency_ratio = max(CR1, CR2, CR3, CR4)

        return CriterionWeights(
            rust_risk=float(W_criteria[0]),
            structural_stability=float(W_criteria[1]),
            repair_history=float(W_criteria[2]),
            rust_eruption_prob=float(W_rust[0]),
            rust_risk_level=float(W_rust[1]),
            rust_chloride=float(W_rust[2]),
            struct_wall_uniformity=float(W_struct[0]),
            struct_crack_index=float(W_struct[1]),
            struct_deformation=float(W_struct[2]),
            repair_count=float(W_repair[0]),
            repair_years_since=float(W_repair[1]),
        )

    def _validate_consistency(self):
        """校验一致性比率，CR>0.1发出警告"""
        if self.consistency_ratio > 0.1:
            logger.warning(
                f"AHP consistency ratio CR={self.consistency_ratio:.4f} > 0.1, "
                f"judgment matrix may be inconsistent!"
            )

    def _normalize_rust_risk(self, data: ArtifactVulnerabilityData) -> Dict[str, float]:
        """粉状锈风险指标归一化到[0,100]分（分越高越脆弱）"""
        s1 = min(100.0, max(0.0, data.eruption_probability * 100.0))
        s2 = min(100.0, max(0.0, (data.risk_level - 1) / 3.0 * 100.0))
        cl_clip = min(10.0, max(0.0, data.chloride_concentration))
        s3 = min(100.0, max(0.0, (cl_clip / 10.0) * 100.0))
        return {"eruption_prob": s1, "risk_level": s2, "chloride": s3}

    def _normalize_struct(self, data: ArtifactVulnerabilityData) -> Dict[str, float]:
        """结构稳定性指标归一化（均匀度高=低脆弱，裂隙多=高脆弱）"""
        uniformity = min(1.0, max(0.0, data.wall_thickness_uniformity))
        s1 = (1.0 - uniformity) * 100.0

        crack = min(1.0, max(0.0, data.crack_index))
        s2 = crack * 100.0

        deform = min(1.0, max(0.0, data.deformation_degree))
        s3 = deform * 100.0

        return {"wall_uniformity": s1, "crack_index": s2, "deformation": s3}

    def _normalize_repair(self, data: ArtifactVulnerabilityData) -> Dict[str, float]:
        """修复历史指标归一化（修复次数多=脆弱，很久未修=积累老化）"""
        missing_fields = []

        repair_count = data.repair_count
        if repair_count is None or (isinstance(repair_count, float) and np.isnan(repair_count)):
            missing_fields.append("repair_count")
            repair_count = 0

        last_repair = data.last_repair_years_ago
        if last_repair is None or (isinstance(last_repair, float) and np.isnan(last_repair)):
            missing_fields.append("last_repair_years_ago")
            last_repair = 2.0

        if missing_fields:
            logger.warning(
                f"Artifact {data.artifact_id}: missing repair fields {missing_fields}, using defaults"
            )

        count_clip = min(10, max(0, int(repair_count)))
        s1 = (count_clip / 10.0) * 100.0

        years_clip = min(50.0, max(0.0, float(last_repair)))
        if years_clip <= 5.0:
            s2 = 20.0
        elif years_clip <= 15.0:
            s2 = 40.0
        elif years_clip <= 25.0:
            s2 = 60.0
        elif years_clip <= 40.0:
            s2 = 80.0
        else:
            s2 = 100.0

        return {"repair_count": s1, "years_since": s2}

    def score(self, data: ArtifactVulnerabilityData) -> VulnerabilityScore:
        """计算单器物的综合脆弱性评分"""
        w = self.weights

        rust_norm = self._normalize_rust_risk(data)
        struct_norm = self._normalize_struct(data)
        repair_norm = self._normalize_repair(data)

        rust_sub = (
            w.rust_eruption_prob * rust_norm["eruption_prob"]
            + w.rust_risk_level * rust_norm["risk_level"]
            + w.rust_chloride * rust_norm["chloride"]
        )

        struct_sub = (
            w.struct_wall_uniformity * struct_norm["wall_uniformity"]
            + w.struct_crack_index * struct_norm["crack_index"]
            + w.struct_deformation * struct_norm["deformation"]
        )

        repair_sub = (
            w.repair_count * repair_norm["repair_count"]
            + w.repair_years_since * repair_norm["years_since"]
        )

        total = (
            w.rust_risk * rust_sub
            + w.structural_stability * struct_sub
            + w.repair_history * repair_sub
        )

        total = min(100.0, max(0.0, total))
        level = self._classify_level(total)

        sub_scores = {
            "rust_risk": round(rust_sub, 2),
            "structural_stability": round(struct_sub, 2),
            "repair_history": round(repair_sub, 2),
        }

        contributions = {
            "rust_risk": round(w.rust_risk * rust_sub / max(total, 1e-6) * 100, 1),
            "structural": round(w.structural_stability * struct_sub / max(total, 1e-6) * 100, 1),
            "repair": round(w.repair_history * repair_sub / max(total, 1e-6) * 100, 1),
        }

        recs = self._generate_recommendations(total, rust_norm, struct_norm, repair_norm)

        return VulnerabilityScore(
            artifact_id=data.artifact_id,
            total_score=round(total, 1),
            level=level,
            sub_scores=sub_scores,
            criterion_contributions=contributions,
            consistency_ratio=round(self.consistency_ratio, 4),
            hall_x=data.hall_x,
            hall_y=data.hall_y,
            calculation_time=datetime.now().isoformat(),
            recommendations=recs,
        )

    def _classify_level(self, score: float) -> VulnerabilityLevel:
        """根据总分分类脆弱等级"""
        if score < 20:
            return VulnerabilityLevel.EXCELLENT
        elif score < 40:
            return VulnerabilityLevel.GOOD
        elif score < 60:
            return VulnerabilityLevel.MODERATE
        elif score < 80:
            return VulnerabilityLevel.POOR
        else:
            return VulnerabilityLevel.DANGEROUS

    def _generate_recommendations(
        self,
        total: float,
        rust_norm: Dict[str, float],
        struct_norm: Dict[str, float],
        repair_norm: Dict[str, float],
    ) -> List[str]:
        """根据各项得分生成保护建议"""
        recs = []

        if rust_norm["eruption_prob"] > 60:
            recs.append("高爆发风险，建议立即开展电化学检测并喷涂缓蚀剂")
        elif rust_norm["chloride"] > 60:
            recs.append("氯离子浓度超标，建议加强展柜密封性并使用活性炭吸附")

        if struct_norm["crack_index"] > 50:
            recs.append("存在明显裂隙，建议进行CT扫描并评估结构加固方案")
        if struct_norm["deformation"] > 40:
            recs.append("形变度较高，建议调整支撑架受力分布并定期监测")

        if repair_norm["years_since"] > 70:
            recs.append("超过25年未修复，建议进行全面健康检查")
        if repair_norm["repair_count"] > 60 and total > 50:
            recs.append("多次修复仍脆弱，建议重新评估保护材料兼容性")

        if total >= 80:
            recs.insert(0, "【紧急】综合脆弱性极高，建议立即移入恒温恒湿库房")
        elif total >= 60:
            recs.insert(0, "综合脆弱性较高，建议24小时连续监测并制定应急方案")
        elif total < 20 and not recs:
            recs.append("保存状态优秀，建议维持现有展陈环境")

        return recs

    def batch_score(self, data_list: List[ArtifactVulnerabilityData]) -> List[VulnerabilityScore]:
        """批量评分"""
        return [self.score(d) for d in data_list]

    def export_heatmap_data(self, scores: List[VulnerabilityScore]) -> List[Dict]:
        """导出热力图数据（供前端展示）"""
        return [
            {
                "artifact_id": s.artifact_id,
                "x": s.hall_x,
                "y": s.hall_y,
                "value": s.total_score,
                "level": s.level.value,
                "color": LEVEL_COLORS[s.level],
                "sub_scores": s.sub_scores,
            }
            for s in scores
        ]


def get_level_info(score: float) -> Tuple[str, str, str]:
    """获取分数对应的等级信息（名称、颜色、中文名称）"""
    if score < 20:
        lvl = VulnerabilityLevel.EXCELLENT
    elif score < 40:
        lvl = VulnerabilityLevel.GOOD
    elif score < 60:
        lvl = VulnerabilityLevel.MODERATE
    elif score < 80:
        lvl = VulnerabilityLevel.POOR
    else:
        lvl = VulnerabilityLevel.DANGEROUS
    return lvl.value, LEVEL_COLORS[lvl], LEVEL_NAMES[lvl]
