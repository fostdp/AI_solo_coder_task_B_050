"""
缓蚀剂残留寿命预测模块测试
覆盖：正常/边界/异常场景
"""
import os
import sys
import numpy as np
import pytest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.algorithms.life_predictor import (
    InhibitorLifetimePredictor,
    LifetimePrediction,
    InhibitorType,
    InhibitorProperties,
    INHIBITOR_PROPERTIES,
    LifeStatus,
    get_life_status_chinese,
    get_life_status_color,
)


def _make_env_history(days=7, temp=22.0, rh=50.0, samples_per_day=24):
    """生成模拟环境历史数据"""
    history = []
    base = datetime.now() - timedelta(days=days)
    for d in range(days):
        for h in range(samples_per_day):
            hour_frac = h / samples_per_day
            t = temp + 2.0 * np.sin(2 * np.pi * hour_frac)
            r = rh + 5.0 * np.sin(2 * np.pi * hour_frac + 1)
            ts = base + timedelta(days=d, hours=h)
            history.append({
                "temperature": round(t, 2),
                "humidity": round(max(0, r), 2),
                "timestamp": ts.isoformat(),
            })
    return history


# ============================================================
# 正常场景
# ============================================================

class TestLifetimeNormal:
    """正常场景测试"""

    def test_high_temp_high_rh_shorter_life(self):
        """高温高湿环境预测寿命 < 低温低湿"""
        pred = InhibitorLifetimePredictor()
        hot_env = _make_env_history(temp=30.0, rh=75.0)
        cool_env = _make_env_history(temp=18.0, rh=40.0)
        spray_date = (datetime.now() - timedelta(days=30)).isoformat()

        hot_result = pred.predict_from_timeseries(
            artifact_id="HOT01", inhibitor_type=InhibitorType.BTA,
            env_history=hot_env, last_spray_date=spray_date,
        )
        cool_result = pred.predict_from_timeseries(
            artifact_id="COOL01", inhibitor_type=InhibitorType.BTA,
            env_history=cool_env, last_spray_date=spray_date,
        )
        assert hot_result.remaining_days < cool_result.remaining_days
        assert hot_result.degradation_rate > cool_result.degradation_rate

    def test_bta_baseline_lifetime(self):
        """BTA在25°C/50%RH下寿命接近基准值(180天)"""
        pred = InhibitorLifetimePredictor()
        env = _make_env_history(temp=25.0, rh=50.0)
        result = pred.predict_from_timeseries(
            artifact_id="BASE01", inhibitor_type=InhibitorType.BTA,
            env_history=env, last_spray_date=datetime.now().isoformat(),
        )
        assert 100 < result.remaining_days < 300

    def test_mbt_longer_than_bta(self):
        """MBO基准寿命(300天) > BTA基准寿命(180天)"""
        pred = InhibitorLifetimePredictor()
        env = _make_env_history(temp=25.0, rh=50.0)
        bta = pred.predict_from_timeseries(
            artifact_id="BTA01", inhibitor_type=InhibitorType.BTA,
            env_history=env, last_spray_date=datetime.now().isoformat(),
        )
        mbo = pred.predict_from_timeseries(
            artifact_id="MBO01", inhibitor_type=InhibitorType.MBO,
            env_history=env, last_spray_date=datetime.now().isoformat(),
        )
        assert mbo.remaining_days > bta.remaining_days

    def test_effectiveness_decreases_over_time(self):
        """喷涂时间越早，当前有效性越低"""
        pred = InhibitorLifetimePredictor()
        env = _make_env_history(temp=25.0, rh=55.0)
        recent = (datetime.now() - timedelta(days=10)).isoformat()
        old = (datetime.now() - timedelta(days=120)).isoformat()

        recent_result = pred.predict_from_timeseries(
            artifact_id="NEW01", inhibitor_type=InhibitorType.BTA,
            env_history=env, last_spray_date=recent,
        )
        old_result = pred.predict_from_timeseries(
            artifact_id="OLD01", inhibitor_type=InhibitorType.BTA,
            env_history=env, last_spray_date=old,
        )
        assert recent_result.effectiveness > old_result.effectiveness

    def test_need_respray_when_expired(self):
        """有效性低于阈值时需重新喷涂"""
        pred = InhibitorLifetimePredictor()
        env = _make_env_history(temp=35.0, rh=80.0)
        old_spray = (datetime.now() - timedelta(days=250)).isoformat()
        result = pred.predict_from_timeseries(
            artifact_id="EXPIRE01", inhibitor_type=InhibitorType.BTA,
            env_history=env, last_spray_date=old_spray,
        )
        if result.remaining_days < 14:
            assert result.need_respray is True
            assert result.status in (LifeStatus.WARNING, LifeStatus.EXPIRED)

    def test_all_inhibitor_types_supported(self):
        """三种缓蚀剂均可预测"""
        pred = InhibitorLifetimePredictor()
        env = _make_env_history()
        for it in InhibitorType:
            result = pred.predict_from_timeseries(
                artifact_id=f"TYPE_{it.value}", inhibitor_type=it,
                env_history=env, last_spray_date=datetime.now().isoformat(),
            )
            assert result is not None
            assert result.remaining_days >= 0
            assert 0.0 <= result.effectiveness <= 1.0

    def test_batch_predict(self):
        """批量预测"""
        pred = InhibitorLifetimePredictor()
        env = _make_env_history()
        items = [
            {"artifact_id": "B01", "inhibitor_type": "BTA", "env_history": env,
             "last_spray_date": datetime.now().isoformat()},
            {"artifact_id": "B02", "inhibitor_type": "AMT", "env_history": env,
             "last_spray_date": datetime.now().isoformat()},
        ]
        results = pred.batch_predict(items)
        assert len(results) == 2
        assert all(isinstance(r, LifetimePrediction) for r in results)

    def test_status_chinese_names(self):
        """所有状态有中文名"""
        for s in LifeStatus:
            name = get_life_status_chinese(s)
            assert len(name) > 0

    def test_status_colors(self):
        """所有状态有颜色"""
        for s in LifeStatus:
            color = get_life_status_color(s)
            assert color.startswith("#")


# ============================================================
# 边界场景
# ============================================================

class TestLifetimeBoundary:
    """边界场景测试"""

    def test_sensor_offline_use_monthly_avg(self):
        """传感器离线时（空环境历史）使用默认均值"""
        pred = InhibitorLifetimePredictor()
        result = pred.predict_from_timeseries(
            artifact_id="OFFLINE01", inhibitor_type=InhibitorType.BTA,
            env_history=[], last_spray_date=datetime.now().isoformat(),
        )
        assert result is not None
        assert result.remaining_days > 0
        assert result.average_temp_7d == 22.0
        assert result.average_rh_7d == 50.0

    def test_zero_humidity(self):
        """0%RH极端干燥环境"""
        pred = InhibitorLifetimePredictor()
        env = _make_env_history(temp=22.0, rh=1.0)
        result = pred.predict_from_timeseries(
            artifact_id="DRY01", inhibitor_type=InhibitorType.BTA,
            env_history=env, last_spray_date=datetime.now().isoformat(),
        )
        assert result.remaining_days > 0

    def test_very_recent_spray(self):
        """刚刚喷涂（0天前）"""
        pred = InhibitorLifetimePredictor()
        env = _make_env_history(temp=22.0, rh=50.0)
        result = pred.predict_from_timeseries(
            artifact_id="JUST01", inhibitor_type=InhibitorType.BTA,
            env_history=env, last_spray_date=datetime.now().isoformat(),
        )
        assert result.effectiveness > 0.8
        assert result.remaining_days > 60

    def test_spray_date_in_future(self):
        """喷涂日期在未来（异常但不应崩溃）"""
        pred = InhibitorLifetimePredictor()
        env = _make_env_history()
        future = (datetime.now() + timedelta(days=30)).isoformat()
        result = pred.predict_from_timeseries(
            artifact_id="FUTURE01", inhibitor_type=InhibitorType.BTA,
            env_history=env, last_spray_date=future,
        )
        assert result is not None

    def test_single_env_data_point(self):
        """仅有1条环境数据"""
        pred = InhibitorLifetimePredictor()
        env = [{"temperature": 25.0, "humidity": 60.0, "timestamp": datetime.now().isoformat()}]
        result = pred.predict_from_timeseries(
            artifact_id="SINGLE01", inhibitor_type=InhibitorType.BTA,
            env_history=env, last_spray_date=datetime.now().isoformat(),
        )
        assert result is not None


# ============================================================
# 异常场景
# ============================================================

class TestLifetimeAbnormal:
    """异常场景测试"""

    def test_temp_over_50c_zero_days(self):
        """温度超过50°C时输出0天（或极短寿命）"""
        pred = InhibitorLifetimePredictor()
        env = _make_env_history(temp=55.0, rh=80.0)
        old_spray = (datetime.now() - timedelta(days=200)).isoformat()
        result = pred.predict_from_timeseries(
            artifact_id="HOT50", inhibitor_type=InhibitorType.BTA,
            env_history=env, last_spray_date=old_spray,
        )
        assert result.remaining_days <= 30 or result.status in (
            LifeStatus.WARNING, LifeStatus.EXPIRED
        )

    def test_invalid_last_spray_date(self):
        """无效的喷涂日期格式"""
        pred = InhibitorLifetimePredictor()
        env = _make_env_history()
        result = pred.predict_from_timeseries(
            artifact_id="BADDATE01", inhibitor_type=InhibitorType.BTA,
            env_history=env, last_spray_date="not-a-date",
        )
        assert result is not None

    def test_missing_last_spray_date(self):
        """缺少喷涂日期"""
        pred = InhibitorLifetimePredictor()
        env = _make_env_history()
        result = pred.predict_from_timeseries(
            artifact_id="NODATE01", inhibitor_type=InhibitorType.BTA,
            env_history=env, last_spray_date=None,
        )
        assert result is not None

    def test_env_data_with_missing_fields(self):
        """环境数据中部分字段缺失"""
        pred = InhibitorLifetimePredictor()
        env = [
            {"temperature": 22.0, "timestamp": datetime.now().isoformat()},
            {"humidity": 50.0, "timestamp": datetime.now().isoformat()},
        ]
        result = pred.predict_from_timeseries(
            artifact_id="MISS01", inhibitor_type=InhibitorType.BTA,
            env_history=env, last_spray_date=datetime.now().isoformat(),
        )
        assert result is not None

    def test_negative_temperature(self):
        """负温度（冷链环境）"""
        pred = InhibitorLifetimePredictor()
        env = _make_env_history(temp=-5.0, rh=30.0)
        result = pred.predict_from_timeseries(
            artifact_id="COLD01", inhibitor_type=InhibitorType.BTA,
            env_history=env, last_spray_date=datetime.now().isoformat(),
        )
        assert result is not None
        assert result.remaining_days > 0

    def test_humidity_correction_non_negative(self):
        """湿度修正因子始终为正"""
        pred = InhibitorLifetimePredictor()
        props = INHIBITOR_PROPERTIES[InhibitorType.BTA]
        for rh in [0.1, 1.0, 50.0, 99.0, 100.0]:
            corr = pred._humidity_correction(rh, props)
            assert corr > 0

    def test_arrhenius_rate_increases_with_temp(self):
        """温度越高，降解速率越快"""
        pred = InhibitorLifetimePredictor()
        props = INHIBITOR_PROPERTIES[InhibitorType.BTA]
        rate_20 = pred._arrhenius_rate(20.0, props)
        rate_30 = pred._arrhenius_rate(30.0, props)
        rate_40 = pred._arrhenius_rate(40.0, props)
        assert rate_20 < rate_30 < rate_40
