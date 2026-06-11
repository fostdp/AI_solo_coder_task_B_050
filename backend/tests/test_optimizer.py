"""
喷涂优化测试
验证 optimizer 微服务的 CFD 简化模型功能
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def sample_target_zones():
    return [
        {
            "zone_id": "Z01",
            "center": {"x": 0.1, "y": 0.1, "z": 0.0},
            "radius": 0.05,
            "severity": 0.8,
            "required_coverage": 0.95
        },
        {
            "zone_id": "Z02",
            "center": {"x": -0.1, "y": -0.05, "z": 0.1},
            "radius": 0.04,
            "severity": 0.6,
            "required_coverage": 0.90
        }
    ]


def test_optimizer_init():
    from app.services.optimizer import SprayOptimizerService

    service = SprayOptimizerService(stream_manager=None)
    assert service.env_temperature == 22.0
    assert service.env_humidity == 45.0
    assert service.env_pressure == 101.3


def test_inhibitor_properties():
    from app.services.optimizer import INHIBITOR_PROPERTIES, InhibitorType

    assert InhibitorType.BTA in INHIBITOR_PROPERTIES
    assert InhibitorType.AMT in INHIBITOR_PROPERTIES
    assert InhibitorType.MBO in INHIBITOR_PROPERTIES

    for inhibitor_type, props in INHIBITOR_PROPERTIES.items():
        assert "molecular_weight" in props
        assert "coverage_efficiency_base" in props
        assert "density_g_cm3" in props
        assert props["coverage_efficiency_base"] > 0
        assert props["density_g_cm3"] > 0


def test_optimize_basic(sample_target_zones):
    from app.services.optimizer import SprayOptimizerService, InhibitorType

    service = SprayOptimizerService(stream_manager=None)

    result = service.optimize(
        artifact_id="test_ding",
        target_zones=sample_target_zones,
        artifact_size={"width": 0.5, "height": 0.6, "depth": 0.4},
        inhibitor_type=InhibitorType.BTA,
        required_coverage=0.90,
        nozzle_count=4,
        max_nozzle_positions=8
    )

    assert result is not None
    assert result.artifact_id == "test_ding"
    assert result.inhibitor_type == InhibitorType.BTA
    assert result.total_volume_ml > 0
    assert result.total_spray_time_s > 0
    assert 0 < result.estimated_coverage <= 1.0
    assert len(result.nozzle_positions) > 0
    assert len(result.zone_results) == len(sample_target_zones)
    assert len(result.spray_path) > 0
    assert "env_temperature" in result.cfd_simulation_summary
    assert "droplet_mean_diameter_um" in result.cfd_simulation_summary


def test_nozzle_positions_valid(sample_target_zones):
    from app.services.optimizer import SprayOptimizerService, NozzlePosition, InhibitorType

    service = SprayOptimizerService(stream_manager=None)
    result = service.optimize(
        artifact_id="test",
        target_zones=sample_target_zones,
        artifact_size={"width": 0.5, "height": 0.6, "depth": 0.4},
        inhibitor_type=InhibitorType.BTA
    )

    for nozzle in result.nozzle_positions:
        assert isinstance(nozzle, NozzlePosition)
        assert isinstance(nozzle.x, (int, float))
        assert isinstance(nozzle.y, (int, float))
        assert isinstance(nozzle.z, (int, float))
        assert nozzle.spray_angle_deg > 0
        assert nozzle.pressure_bar > 0
        assert nozzle.dwell_time_s > 0


def test_zone_results_valid(sample_target_zones):
    from app.services.optimizer import SprayOptimizerService, SprayZoneResult, InhibitorType

    service = SprayOptimizerService(stream_manager=None)
    result = service.optimize(
        artifact_id="test",
        target_zones=sample_target_zones,
        artifact_size={"width": 0.5, "height": 0.6, "depth": 0.4},
        inhibitor_type=InhibitorType.AMT
    )

    for zone in result.zone_results:
        assert isinstance(zone, SprayZoneResult)
        assert zone.zone_id is not None
        assert 0 < zone.predicted_coverage <= 1.0
        assert zone.estimated_volume_ml > 0
        assert zone.spray_time_s > 0
        assert zone.pass_count >= 1


def test_spray_path_structure(sample_target_zones):
    from app.services.optimizer import SprayOptimizerService, InhibitorType

    service = SprayOptimizerService(stream_manager=None)
    result = service.optimize(
        artifact_id="test",
        target_zones=sample_target_zones,
        artifact_size={"width": 0.5, "height": 0.6, "depth": 0.4},
        inhibitor_type=InhibitorType.MBO
    )

    assert isinstance(result.spray_path, list)
    for step in result.spray_path:
        assert "action" in step
        assert step["action"] in ("move", "spray")
        assert "step" in step


def test_droplet_size_estimation():
    from app.services.optimizer import SprayOptimizerService, INHIBITOR_PROPERTIES, InhibitorType

    service = SprayOptimizerService(stream_manager=None)

    for inh_type in [InhibitorType.BTA, InhibitorType.AMT, InhibitorType.MBO]:
        props = INHIBITOR_PROPERTIES[inh_type]
        size = service._estimate_droplet_size(props)
        assert size > 0
        assert isinstance(size, float)


def test_evaporation_estimation():
    from app.services.optimizer import SprayOptimizerService, INHIBITOR_PROPERTIES, InhibitorType

    service = SprayOptimizerService(stream_manager=None)

    for inh_type in [InhibitorType.BTA, InhibitorType.AMT, InhibitorType.MBO]:
        props = INHIBITOR_PROPERTIES[inh_type]
        evap = service._estimate_evaporation(props)
        assert evap >= 0
        assert isinstance(evap, float)


def test_different_inhibitors_different_results(sample_target_zones):
    from app.services.optimizer import SprayOptimizerService, InhibitorType

    service = SprayOptimizerService(stream_manager=None)

    result_bta = service.optimize(
        artifact_id="test",
        target_zones=sample_target_zones,
        artifact_size={"width": 0.5, "height": 0.6, "depth": 0.4},
        inhibitor_type=InhibitorType.BTA
    )

    result_amt = service.optimize(
        artifact_id="test",
        target_zones=sample_target_zones,
        artifact_size={"width": 0.5, "height": 0.6, "depth": 0.4},
        inhibitor_type=InhibitorType.AMT
    )

    assert result_bta.total_volume_ml != result_amt.total_volume_ml or \
           result_bta.estimated_coverage != result_amt.estimated_coverage


def test_stats():
    from app.services.optimizer import SprayOptimizerService

    service = SprayOptimizerService(stream_manager=None)
    stats = service.get_stats()

    assert "optimized" in stats
    assert "failed" in stats
    assert "is_running" in stats
    assert "inhibitors" in stats
