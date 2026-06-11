"""
系统验证脚本
测试核心算法模块的功能正确性
运行: python verify_system.py
"""

import sys
import os
import numpy as np
import json

from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))
os.chdir(os.path.join(os.path.dirname(__file__), 'backend'))

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

load_dotenv()


def test_wavelet_features():
    print("\n" + "=" * 60)
    print("测试1: 小波包分解特征提取")
    print("=" * 60)
    try:
        from app.algorithms.wavelet_features import (
            WaveletPacketFeatureExtractor, features_to_feature_vector
        )

        extractor = WaveletPacketFeatureExtractor(
            wavelet="db4", max_level=4, sampling_rate=1000
        )

        np.random.seed(42)
        n = 1024
        t = np.arange(n) / 1000
        v_noise = np.random.normal(0, 15e-6, n)
        i_noise = np.random.normal(0, 3e-8, n)
        for freq in [0.5, 5, 50]:
            v_noise += 5e-6 * np.sin(2 * np.pi * freq * t)
            i_noise += 1e-8 * np.sin(2 * np.pi * freq * t)

        # 注入异常瞬态
        for _ in range(5):
            pos = np.random.randint(100, n - 100)
            v_noise[pos:pos + 20] += 100e-6 * np.exp(-0.5 * ((np.arange(20) - 10) / 5) ** 2)

        features = extractor.extract(v_noise, i_noise, area_cm2=1.0)

        print(f"  总能量: {features.total_energy:.4e}")
        print(f"  噪声电阻 Rn: {features.noise_resistance:.2f} Ω·cm²")
        print(f"  点蚀指数: {features.pitting_index:.4f}")
        print(f"  小波熵: {features.wavelet_entropy:.4f}")
        print(f"  频带能量数: {len(features.band_energies)}")
        print(f"  统计特征数: {len(features.statistical_features)}")
        print(f"  电压偏度: {features.statistical_features.get('V_skew', 0):.4f}")
        print(f"  电压峰度: {features.statistical_features.get('V_kurtosis', 0):.4f}")

        vector, names = features_to_feature_vector(features)
        print(f"  特征向量维度: {vector.shape[0]}")

        assert features.noise_resistance > 0, "噪声电阻计算错误"
        assert len(features.band_energies) > 0, "频带能量提取失败"
        assert vector.ndim == 1, "特征向量维度错误"
        print("  [OK] 小波包特征提取测试通过")
        return True
    except Exception as e:
        print(f"  [FAIL] 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_prediction_model():
    print("\n" + "=" * 60)
    print("测试2: 随机森林粉状锈爆发预测模型")
    print("=" * 60)
    try:
        from app.algorithms.rust_prediction_model import RustPredictionModel

        model = RustPredictionModel()

        # 模拟正常样本
        wavelet_normal = {
            "statistical_features": {
                "V_mean": 0, "V_std": 1e-5, "V_rms": 1e-5,
                "V_skew": 0.1, "V_kurtosis": 3.0, "V_peak_to_peak": 6e-5, "V_cv": 1.0,
                "I_mean": 0, "I_std": 2e-8, "I_rms": 2e-8,
                "I_skew": 0.05, "I_kurtosis": 3.0, "I_peak_to_peak": 1.2e-7, "I_cv": 1.0,
                "cross_corr": 0.05
            },
            "band_energy_ratios": {f"band_{i}": 0.05 for i in range(40)},
            "wavelet_entropy": 4.2,
            "noise_resistance": 450.0,
            "pitting_index": 0.8
        }

        menv_normal = {
            "temperature": 22.0, "humidity": 45.0,
            "chloride_concentration": 1.2, "sulfur_dioxide": 12.0,
            "nitrogen_oxides": 6.0, "formaldehyde": 10.0
        }

        result_normal = model.predict(
            "BRZ00001", wavelet_normal, menv_normal, target_window="24h"
        )
        print(f"  正常样本 - 爆发概率: {result_normal.eruption_probability:.4f}")
        print(f"  正常样本 - 风险等级: {result_normal.risk_level} (1低~4极高)")
        print(f"  正常样本 - 风险区域数: {len(result_normal.risk_zones)}")
        print(f"  正常样本 - 模型版本: {result_normal.model_version}")

        # 模拟高风险样本
        wavelet_risk = {
            "statistical_features": {
                "V_mean": 0, "V_std": 5e-5, "V_rms": 5e-5,
                "V_skew": 1.8, "V_kurtosis": 8.0, "V_peak_to_peak": 3e-4, "V_cv": 1.2,
                "I_mean": 0, "I_std": 8e-8, "I_rms": 8e-8,
                "I_skew": 2.5, "I_kurtosis": 10.0, "I_peak_to_peak": 5e-7, "I_cv": 1.5,
                "cross_corr": 0.3
            },
            "band_energy_ratios": {f"band_{i}": 0.02 + i * 0.002 for i in range(40)},
            "wavelet_entropy": 2.8,
            "noise_resistance": 65.0,
            "pitting_index": 3.5
        }

        menv_risk = {
            "temperature": 28.0, "humidity": 68.0,
            "chloride_concentration": 5.5, "sulfur_dioxide": 45.0,
            "nitrogen_oxides": 20.0, "formaldehyde": 25.0
        }

        result_risk = model.predict(
            "BRZ00002", wavelet_risk, menv_risk, target_window="24h"
        )
        print(f"  风险样本 - 爆发概率: {result_risk.eruption_probability:.4f}")
        print(f"  风险样本 - 风险等级: {result_risk.risk_level} (1低~4极高)")
        print(f"  风险样本 - 风险区域数: {len(result_risk.risk_zones)}")
        print(f"  风险样本 - 特征贡献TOP3: " +
              f"{list(result_risk.feature_contributions.items())[:3]}")

        assert 0 <= result_normal.eruption_probability <= 1.0, "概率范围错误"
        assert 0 <= result_risk.eruption_probability <= 1.0, "概率范围错误"
        assert 1 <= result_normal.risk_level <= 4, "风险等级错误"
        assert 1 <= result_risk.risk_level <= 4, "风险等级错误"
        assert len(result_normal.risk_zones) >= 0, "风险区域数据错误"
        assert isinstance(result_normal.model_version, str) and len(result_normal.model_version) > 0, "模型版本错误"
        print("  [OK] 随机森林预测模型测试通过")
        return True
    except Exception as e:
        print(f"  [FAIL] 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_spray_optimizer():
    print("\n" + "=" * 60)
    print("测试3: CFD简化缓蚀剂喷涂覆盖优化")
    print("=" * 60)
    try:
        from app.algorithms.spray_optimizer import (
            CFDSimplifiedSprayOptimizer, InhibitorType, INHIBITOR_PROPERTIES
        )

        optimizer = CFDSimplifiedSprayOptimizer()

        target_zones = [
            {
                "zone_id": "Z01",
                "center": {"x": -0.15, "y": 0.05, "z": 0},
                "radius": 0.06,
                "severity": 0.8,
                "required_coverage": 0.95
            },
            {
                "zone_id": "Z02",
                "center": {"x": 0.1, "y": -0.02, "z": 0.08},
                "radius": 0.04,
                "severity": 0.6,
                "required_coverage": 0.90
            },
            {
                "zone_id": "Z03",
                "center": {"x": 0.05, "y": 0.12, "z": -0.06},
                "radius": 0.05,
                "severity": 0.9,
                "required_coverage": 0.98
            }
        ]

        for inhib in [InhibitorType.BTA, InhibitorType.AMT, InhibitorType.MBO]:
            result = optimizer.optimize(
                artifact_id="BRZ00001",
                target_zones=target_zones,
                artifact_size={"width": 0.5, "height": 0.6, "depth": 0.4},
                inhibitor_type=inhib,
                required_coverage=0.90,
                nozzle_count=5,
                max_nozzle_positions=24
            )

            print(f"\n  [{inhib.value}] {INHIBITOR_PROPERTIES[inhib]['coverage_efficiency_base']:.0%}基础效率:")
            print(f"    喷嘴位置数: {len(result.nozzle_positions)}")
            print(f"    预计总用量: {result.total_volume_ml:.2f} mL")
            print(f"    预计总耗时: {result.total_spray_time_s:.1f} s")
            print(f"    预计平均覆盖度: {result.estimated_coverage:.2%}")
            print(f"    路径步数: {len(result.spray_path)}")
            print(f"    液滴平均直径: {result.cfd_simulation_summary['droplet_mean_diameter_um']:.1f} μm")
            print(f"    分区覆盖: " + ", ".join(
                [f"{z.zone_id}={z.predicted_coverage:.1%}" for z in result.zone_results]
            ))

            assert len(result.nozzle_positions) > 0, "未生成喷嘴位置"
            assert result.estimated_coverage > 0.5, "覆盖度过低"
            assert result.total_volume_ml > 0, "用量计算错误"

        print("\n  [OK] 喷涂优化模型测试通过")
        return True
    except Exception as e:
        print(f"  [FAIL] 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_alert_dispatcher():
    print("\n" + "=" * 60)
    print("测试4: 告警推送模块 (模拟模式)")
    print("=" * 60)
    try:
        import asyncio
        from datetime import datetime
        from app.alerts.dispatcher import (
            AlertMessage, AlertType, AlertSeverity, dispatcher
        )

        async def run_alert_tests():
            cases = [
                (AlertType.RN_LOW, AlertSeverity.WARNING, 100, 78.5, "Ω·cm²"),
                (AlertType.CL_HIGH, AlertSeverity.CRITICAL, 3, 5.8, "μg/m³"),
                (AlertType.RUST_PREDICTION, AlertSeverity.CRITICAL, 0.5, 0.72, "probability"),
                (AlertType.RUST_ERUPTION, AlertSeverity.EMERGENCY, 0.5, 0.85, "ratio"),
            ]

            for idx, (atype, sev, th, val, unit) in enumerate(cases):
                alert = AlertMessage(
                    alert_id=idx + 1,
                    artifact_id=f"BRZ{idx+1:05d}",
                    artifact_name=f"测试青铜器#{idx+1}",
                    alert_type=atype,
                    severity=sev,
                    threshold_value=th,
                    actual_value=val,
                    unit=unit,
                    message="系统验证测试告警",
                    alert_time=datetime.utcnow(),
                    risk_level=sev.value
                )

                result = await dispatcher.dispatch(alert)
                print(f"  [{atype.value} S{sev.value}] "
                      f"器物:BRZ{idx+1:05d} 值:{val}{unit} (阈值:{th}) "
                      f"-> 推送:WeChat={'[OK]' if result.get('wecom') else '[SKIP]'} "
                      f"SMS={'[OK]' if result.get('sms') else '[SKIP]'}")

                suggestion = dispatcher.build_alert_suggestion(
                    atype, sev, val, th
                )
                print(f"    处置建议: {suggestion}")

        asyncio.run(run_alert_tests())
        print("\n  [OK] 告警模块测试通过")
        return True
    except Exception as e:
        print(f"  [FAIL] 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_config_and_imports():
    print("\n" + "=" * 60)
    print("测试5: 配置和模块导入")
    print("=" * 60)
    try:
        from app.config import get_settings
        settings = get_settings()
        print(f"  DB Host: {settings.DB_HOST}")
        print(f"  MQTT Broker: {settings.MQTT_BROKER}:{settings.MQTT_PORT}")
        print(f"  Rn阈值: {settings.NOISE_RESISTANCE_THRESHOLD} Ω·cm²")
        print(f"  Cl⁻阈值: {settings.CHLORIDE_THRESHOLD} μg/m³")
        print(f"  上报间隔: {settings.REPORT_INTERVAL}s ({settings.REPORT_INTERVAL/60}min)")

        from app.database import get_db
        print("  数据库模块导入OK")

        from app.routers import api
        print("  API路由模块导入OK")

        from app import main
        print("  FastAPI主应用模块导入OK")

        print("  [OK] 配置和导入测试通过")
        return True
    except Exception as e:
        print(f"  [FAIL] 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("\n" + "╔" + "═" * 58 + "╗")
    print("║" + "古代青铜器粉状锈爆发预警系统 - 核心算法验证".center(58) + "║")
    print("╚" + "═" * 58 + "╝")

    tests = [
        ("配置与导入", test_config_and_imports),
        ("小波包特征提取", test_wavelet_features),
        ("随机森林预测模型", test_prediction_model),
        ("CFD喷涂优化", test_spray_optimizer),
        ("告警推送模块", test_alert_dispatcher),
    ]

    passed = 0
    failed = 0

    for name, test_fn in tests:
        try:
            if test_fn():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"\n[异常] {name}: {e}")
            failed += 1

    print("\n" + "=" * 60)
    print("验证总结")
    print("=" * 60)
    print(f"  总测试项: {len(tests)}")
    print(f"  [OK] 通过: {passed}")
    print(f"  [FAIL] 失败: {failed}")
    print(f"  通过率: {passed/len(tests)*100:.1f}%")

    if failed == 0:
        print("\n[GOOD] 全部核心算法模块验证通过！")
        print("\n下一步操作:")
        print("  1. 启动 TimescaleDB 并执行 database/init_timescaledb.sql")
        print("  2. cd backend && pip install -r requirements.txt")
        print("  3. cp .env.example .env 并配置数据库和MQTT")
        print("  4. python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload")
        print("  5. (可选) python mqtt_simulator.py --fast 快速模拟数据")
        print("  6. cd frontend && npm install && npm run dev")
    else:
        print("\n[WARN] 存在失败项，请检查错误信息")

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

