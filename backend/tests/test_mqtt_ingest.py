"""
MQTT Ingest 服务测试
验证 mqtt_ingest 微服务的消息处理与缓存功能
"""
import os
import sys
import pytest
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def ingest_service():
    from app.services.mqtt_ingest import MQTTIngestService

    service = MQTTIngestService(stream_manager=None)
    return service


def test_ingest_service_init(ingest_service):
    assert ingest_service is not None
    assert isinstance(ingest_service.last_ecn_data, dict)
    assert isinstance(ingest_service.last_menv_data, dict)
    assert len(ingest_service.last_ecn_data) == 0
    assert len(ingest_service.last_menv_data) == 0


def test_ingest_update_cache_ecn(ingest_service):
    payload = {
        "sensor_id": "ecn_001",
        "artifact_id": "ding_001",
        "noise_resistance": 150.0,
        "pitting_index": 0.8,
        "std_voltage": 0.005,
        "std_current": 1e-6,
        "skewness_voltage": 0.1,
        "kurtosis_voltage": 3.0
    }

    ingest_service._update_cache("electrochemical", "ding_001", payload)

    assert "ding_001" in ingest_service.last_ecn_data
    data = ingest_service.last_ecn_data["ding_001"]
    assert data["noise_resistance"] == 150.0
    assert data["pitting_index"] == 0.8
    assert data["std_voltage"] == 0.005


def test_ingest_update_cache_menv(ingest_service):
    payload = {
        "sensor_id": "menv_001",
        "artifact_id": "ding_001",
        "temperature": 23.5,
        "humidity": 55.0,
        "chloride_concentration": 2.0,
        "sulfur_dioxide": 15.0,
        "nitrogen_oxides": 8.0
    }

    ingest_service._update_cache("microenv", "ding_001", payload)

    assert "ding_001" in ingest_service.last_menv_data
    data = ingest_service.last_menv_data["ding_001"]
    assert data["temperature"] == 23.5
    assert data["humidity"] == 55.0
    assert data["chloride_concentration"] == 2.0


def test_get_realtime_data(ingest_service):
    ingest_service.last_ecn_data["a1"] = {"noise_resistance": 100}
    ingest_service.last_menv_data["a1"] = {"temperature": 22}
    ingest_service.last_ecn_data["a2"] = {"noise_resistance": 200}

    all_data = ingest_service.get_realtime_data()
    assert "a1" in all_data
    assert "a2" in all_data
    assert "ecn" in all_data["a1"]
    assert "menv" in all_data["a1"]

    single = ingest_service.get_realtime_data("a1")
    assert len(single) == 1
    assert "a1" in single


def test_ingest_unknown_sensor_type(ingest_service):
    payload = {"sensor_id": "x_001", "artifact_id": "test"}
    ingest_service._update_cache("unknown_type", "test", payload)

    assert "test" not in ingest_service.last_ecn_data
    assert "test" not in ingest_service.last_menv_data


def test_malfunction_status(ingest_service):
    import asyncio

    payload = {
        "sensor_id": "ecn_002",
        "artifact_id": "ding_002",
        "status": "malfunction",
        "error_code": "E1001"
    }

    result = asyncio.run(ingest_service._handle_message("electrochemical", payload))
    assert "ding_002" not in ingest_service.last_ecn_data


def test_mqtt_client_init():
    from app.services.mqtt_ingest import MQTTIngestService

    service = MQTTIngestService(stream_manager=None)
    service._init_mqtt_client()

    if service.mqtt_client is not None:
        assert hasattr(service.mqtt_client, 'on_connect')
        assert hasattr(service.mqtt_client, 'on_message')


def test_port_check():
    from app.services.mqtt_ingest import MQTTIngestService

    service = MQTTIngestService(stream_manager=None)
    result = service._check_port_open("localhost", 9999, timeout=0.1)
    assert isinstance(result, bool)
