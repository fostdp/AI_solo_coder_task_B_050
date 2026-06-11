"""
缓蚀剂残留寿命预测模块
基于Arrhenius方程和展柜微环境温湿度，预测缓蚀剂保护膜的有效剩余天数

设计说明：
- 核心方程：Arrhenius公式 k = A * exp(-Ea/(R*T))
- 湿度修正：RH指数修正降解速率
- 支持BTA/AMT/MBO三种缓蚀剂
- 寿命更新周期：每小时重新计算
- 输入：最近7天的温湿度时间序列 + 最近一次喷涂日期
- 输出：剩余有效天数、当前降解速率、失效预警
"""

import os
import math
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from enum import Enum
from datetime import datetime, timedelta

import numpy as np

logger = logging.getLogger("life_predictor")


class InhibitorType(str, Enum):
    BTA = "BTA"     # 苯并三氮唑
    AMT = "AMT"     # 2-氨基-5-巯基-1,3,4-噻二唑
    MBO = "MBO"     # 2-巯基苯并恶唑


class LifeStatus(str, Enum):
    EXCELLENT = "excellent"    # 保护膜完好
    GOOD = "good"              # 状态良好
    DEGRADING = "degrading"    # 正在降解
    WARNING = "warning"        # 即将失效
    EXPIRED = "expired"        # 已失效


@dataclass
class InhibitorProperties:
    name_zh: str
    activation_energy_kJ_mol: float      # Ea (kJ/mol)
    pre_exponential_factor: float        # A (day⁻¹)
    moisture_sensitivity: float          # b (无量纲，RH敏感性)
    reference_RH: float                  # 参考湿度 (%)
    baseline_lifetime_days_25C: float    # 25°C下基准寿命 (天)
    threshold_effectiveness: float       # 有效性阈值 (0-1)
    coverage_coef: float                 # 初始覆盖率系数


INHIBITOR_PROPERTIES: Dict[InhibitorType, InhibitorProperties] = {
    InhibitorType.BTA: InhibitorProperties(
        name_zh="苯并三氮唑(BTA)",
        activation_energy_kJ_mol=85.0,
        pre_exponential_factor=5.2e12,
        moisture_sensitivity=0.8,
        reference_RH=50.0,
        baseline_lifetime_days_25C=180.0,
        threshold_effectiveness=0.3,
        coverage_coef=0.95,
    ),
    InhibitorType.AMT: InhibitorProperties(
        name_zh="氨基巯基噻二唑(AMT)",
        activation_energy_kJ_mol=95.0,
        pre_exponential_factor=3.8e13,
        moisture_sensitivity=0.6,
        reference_RH=50.0,
        baseline_lifetime_days_25C=240.0,
        threshold_effectiveness=0.35,
        coverage_coef=0.92,
    ),
    InhibitorType.MBO: InhibitorProperties(
        name_zh="巯基苯并恶唑(MBO)",
        activation_energy_kJ_mol=105.0,
        pre_exponential_factor=1.5e15,
        moisture_sensitivity=0.5,
        reference_RH=50.0,
        baseline_lifetime_days_25C=300.0,
        threshold_effectiveness=0.32,
        coverage_coef=0.90,
    ),
}


@dataclass
class MicroEnvSnapshot:
    temperature: float      # °C
    humidity: float         # % RH
    timestamp: datetime


@dataclass
class LifetimePrediction:
    artifact_id: str
    inhibitor_type: InhibitorType
    remaining_days: float
    effectiveness: float
    degradation_rate: float
    status: LifeStatus
    last_spray_date: Optional[str]
    average_temp_7d: float
    average_rh_7d: float
    need_respray: bool
    prediction_time: str
    warning_level: int = 0
    detail: Dict = field(default_factory=dict)


class InhibitorLifetimePredictor:
    """基于Arrhenius方程的缓蚀剂寿命预测器"""

    R_GAS = 8.314e-3  # kJ/(mol·K)

    def __init__(self, model_dir: str = "app/models"):
        self.model_dir = model_dir
        self._cache: Dict[str, Dict] = {}
        logger.info("Inhibitor Lifetime Predictor initialized")

    def _arrhenius_rate(self, temp_celsius: float, props: InhibitorProperties) -> float:
        """计算温度T下的Arrhenius降解速率 (day⁻¹)"""
        T_K = temp_celsius + 273.15
        Ea_R = props.activation_energy_kJ_mol / self.R_GAS
        k = props.pre_exponential_factor * math.exp(-Ea_R / T_K)
        return k

    def _humidity_correction(self, rh_percent: float, props: InhibitorProperties) -> float:
        """湿度修正因子：(RH/RH_ref)^b"""
        rh_eff = max(rh_percent, 1.0)
        ref = max(props.reference_RH, 1.0)
        return (rh_eff / ref) ** props.moisture_sensitivity

    def _effective_degradation_rate(self, temp: float, rh: float,
                                     props: InhibitorProperties) -> float:
        """综合温度和湿度的有效降解速率"""
        k_basic = self._arrhenius_rate(temp, props)
        k_humidity = k_basic * self._humidity_correction(rh, props)
        return k_humidity

    def _calibrate_rate(self, rate_raw: float, props: InhibitorProperties) -> float:
        """校准降解速率，使其在25°C/50%RH下符合基准寿命"""
        T_ref = 25.0
        RH_ref = props.reference_RH
        k_ref_raw = self._effective_degradation_rate(T_ref, RH_ref, props)
        k_ref_target = 1.0 / props.baseline_lifetime_days_25C
        if k_ref_raw > 1e-10:
            calibrate_factor = k_ref_target / k_ref_raw
        else:
            calibrate_factor = 1.0
        return rate_raw * calibrate_factor

    def predict_from_timeseries(
        self,
        artifact_id: str,
        inhibitor_type: InhibitorType,
        env_history: List[Dict],
        last_spray_date: Optional[str] = None,
        initial_coverage: Optional[float] = None,
    ) -> LifetimePrediction:
        """基于7天温湿度时间序列预测剩余寿命

        Args:
            env_history: List[{temperature, humidity, timestamp}]
            last_spray_date: ISO格式日期字符串
            initial_coverage: 初始覆盖率(0-1)，None则从属性推断
        """
        props = INHIBITOR_PROPERTIES.get(inhibitor_type, INHIBITOR_PROPERTIES[InhibitorType.BTA])

        avg_T, avg_RH = self._average_from_history(env_history)
        avg_rate_raw = self._effective_degradation_rate(avg_T, avg_RH, props)
        avg_rate = self._calibrate_rate(avg_rate_raw, props)

        if last_spray_date:
            try:
                spray_dt = datetime.fromisoformat(last_spray_date)
                days_elapsed = (datetime.now() - spray_dt).total_seconds() / 86400.0
                days_elapsed = max(0.0, days_elapsed)
            except Exception:
                days_elapsed = 0.0
        else:
            days_elapsed = self._estimate_days_since_spray(artifact_id, env_history)

        init_cov = initial_coverage if initial_coverage is not None else props.coverage_coef

        accumulated_degradation = avg_rate * days_elapsed

        current_effectiveness = max(0.0, init_cov * math.exp(-accumulated_degradation))
        current_effectiveness = min(1.0, current_effectiveness)

        if avg_rate < 1e-8:
            remaining_days = 3650.0
        else:
            if current_effectiveness > props.threshold_effectiveness:
                remaining_days = (
                    math.log(current_effectiveness / props.threshold_effectiveness)
                    / avg_rate
                )
            else:
                remaining_days = 0.0

            remaining_days = max(0.0, min(remaining_days, 3650.0))

        status, warning_level = self._classify_status(
            remaining_days, current_effectiveness, props
        )
        need_respray = status in (LifeStatus.WARNING, LifeStatus.EXPIRED)

        return LifetimePrediction(
            artifact_id=artifact_id,
            inhibitor_type=inhibitor_type,
            remaining_days=round(remaining_days, 1),
            effectiveness=round(current_effectiveness, 4),
            degradation_rate=round(avg_rate, 6),
            status=status,
            last_spray_date=last_spray_date,
            average_temp_7d=round(avg_T, 2),
            average_rh_7d=round(avg_RH, 2),
            need_respray=need_respray,
            prediction_time=datetime.now().isoformat(),
            warning_level=warning_level,
            detail={
                "inhibitor_name": props.name_zh,
                "init_coverage": init_cov,
                "days_elapsed": round(days_elapsed, 1),
                "accumulated_degradation": round(accumulated_degradation, 4),
                "threshold_effectiveness": props.threshold_effectiveness,
                "baseline_lifetime_days_25C": props.baseline_lifetime_days_25C,
            },
        )

    def _average_from_history(self, env_history: List[Dict]) -> Tuple[float, float]:
        """从历史数据计算平均温湿度"""
        if not env_history:
            return 22.0, 50.0

        temps = []
        rhs = []
        for env in env_history:
            try:
                t = float(env.get("temperature", 0))
                h = float(env.get("humidity", 0))
                if t > 0 and h > 0:
                    temps.append(t)
                    rhs.append(h)
            except Exception:
                continue

        if not temps:
            return 22.0, 50.0

        return float(np.mean(temps)), float(np.mean(rhs))

    def _estimate_days_since_spray(self, artifact_id: str,
                                    env_history: List[Dict]) -> float:
        """无喷涂日期时，根据缓存估计已用天数"""
        cached = self._cache.get(artifact_id, {})
        prev_days = cached.get("days_elapsed", 0.0)
        cached["days_elapsed"] = prev_days + (1 / 24)
        self._cache[artifact_id] = cached
        return min(cached["days_elapsed"], 300.0)

    def _classify_status(
        self,
        remaining_days: float,
        effectiveness: float,
        props: InhibitorProperties,
    ) -> Tuple[LifeStatus, int]:
        """根据剩余寿命和有效性分类状态"""
        if effectiveness <= props.threshold_effectiveness:
            return LifeStatus.EXPIRED, 4

        remaining_ratio = effectiveness / props.coverage_coef

        if remaining_ratio >= 0.8 and remaining_days >= 90:
            return LifeStatus.EXCELLENT, 0
        elif remaining_ratio >= 0.6 and remaining_days >= 30:
            return LifeStatus.GOOD, 1
        elif remaining_ratio >= 0.45 and remaining_days >= 14:
            return LifeStatus.DEGRADING, 2
        else:
            return LifeStatus.WARNING, 3

    def batch_predict(
        self,
        items: List[Dict],
    ) -> List[LifetimePrediction]:
        """批量预测多件器物的寿命"""
        results = []
        for item in items:
            try:
                result = self.predict_from_timeseries(
                    artifact_id=item["artifact_id"],
                    inhibitor_type=InhibitorType(item.get("inhibitor_type", "BTA")),
                    env_history=item.get("env_history", []),
                    last_spray_date=item.get("last_spray_date"),
                    initial_coverage=item.get("initial_coverage"),
                )
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to predict lifetime for {item.get('artifact_id')}: {e}")
        return results


def get_life_status_chinese(status: LifeStatus) -> str:
    """状态中文名称"""
    names = {
        LifeStatus.EXCELLENT: "保护膜完好",
        LifeStatus.GOOD: "状态良好",
        LifeStatus.DEGRADING: "正在降解",
        LifeStatus.WARNING: "即将失效",
        LifeStatus.EXPIRED: "已失效",
    }
    return names.get(status, "未知")


def get_life_status_color(status: LifeStatus) -> str:
    """状态显示颜色"""
    colors = {
        LifeStatus.EXCELLENT: "#10B981",
        LifeStatus.GOOD: "#3B82F6",
        LifeStatus.DEGRADING: "#F59E0B",
        LifeStatus.WARNING: "#EF4444",
        LifeStatus.EXPIRED: "#991B1B",
    }
    return colors.get(status, "#6B7280")
