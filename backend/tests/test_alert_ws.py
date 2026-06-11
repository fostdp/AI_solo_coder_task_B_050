"""
告警 & WebSocket 服务测试
验证 alert_ws 微服务的告警处理与推送功能
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_alert_templates_exist():
    from app.services.alert_ws import ALERT_TEMPLATES, AlertType

    assert AlertType.RN_LOW in ALERT_TEMPLATES
    assert AlertType.CL_HIGH in ALERT_TEMPLATES
    assert AlertType.SO2_HIGH in ALERT_TEMPLATES
    assert AlertType.TEMP_HIGH in ALERT_TEMPLATES
    assert AlertType.HUMIDITY_HIGH in ALERT_TEMPLATES
    assert AlertType.RUST_ERUPTION in ALERT_TEMPLATES
    assert AlertType.RUST_PREDICTION in ALERT_TEMPLATES

    for alert_type, tpl in ALERT_TEMPLATES.items():
        assert "description" in tpl
        assert "suggestion" in tpl
        assert isinstance(tpl["description"], str)
        assert len(tpl["description"]) > 0


def test_alert_severity_levels():
    from app.services.alert_ws import AlertSeverity

    severities = list(AlertSeverity)
    assert len(severities) == 4
    assert AlertSeverity.INFO in severities
    assert AlertSeverity.WARNING in severities
    assert AlertSeverity.CRITICAL in severities
    assert AlertSeverity.EMERGENCY in severities


def test_websocket_manager_init():
    from app.services.alert_ws import WebSocketManager

    ws_mgr = WebSocketManager()
    assert ws_mgr.connection_count() == 0
    assert len(ws_mgr.active_connections) == 0


def test_alert_dispatcher_init():
    from app.services.alert_ws import AlertDispatcher

    dispatcher = AlertDispatcher()
    assert dispatcher.wecom_url is not None
    assert dispatcher.sms_api_url is not None


def test_build_alert_suggestion():
    from app.services.alert_ws import AlertDispatcher, AlertType, AlertSeverity

    dispatcher = AlertDispatcher()

    suggestion = dispatcher.build_alert_suggestion(
        AlertType.CL_HIGH, AlertSeverity.CRITICAL, 5.0, 3.0
    )
    assert isinstance(suggestion, str)
    assert len(suggestion) > 0


def test_alert_ws_service_init():
    from app.services.alert_ws import AlertWSService

    service = AlertWSService(stream_manager=None)
    assert service.ws_mgr is not None
    assert service.dispatcher is not None
    assert isinstance(service.alert_cooldown, dict)
    assert service._cooldown_seconds > 0


def test_alert_cooldown_logic():
    from app.services.alert_ws import AlertWSService

    service = AlertWSService(stream_manager=None)
    service._cooldown_seconds = 900

    import time
    key = "test_artifact_rn_low"
    now = time.time()
    service.alert_cooldown[key] = now - 1000
    assert now - service.alert_cooldown[key] > service._cooldown_seconds

    service.alert_cooldown[key] = now
    assert now - service.alert_cooldown[key] < service._cooldown_seconds


def test_get_stats():
    from app.services.alert_ws import AlertWSService

    service = AlertWSService(stream_manager=None)
    stats = service.get_stats()

    assert "alerts_received" in stats
    assert "alerts_pushed" in stats
    assert "alerts_cooldown_skipped" in stats
    assert "ws_broadcasts" in stats
    assert "is_running" in stats
    assert "ws_connections" in stats


def test_alert_message_dataclass():
    from app.services.alert_ws import AlertMessage, AlertType, AlertSeverity
    from datetime import datetime

    msg = AlertMessage(
        alert_id=1,
        artifact_id="test_001",
        artifact_name="Test Ding",
        alert_type=AlertType.RN_LOW,
        severity=AlertSeverity.WARNING,
        threshold_value=100.0,
        actual_value=50.0,
        unit="Ω·cm²",
        message="Test alert",
        alert_time=datetime.now(),
        risk_level=2,
        suggestion="Test suggestion"
    )

    assert msg.alert_id == 1
    assert msg.artifact_id == "test_001"
    assert msg.severity == AlertSeverity.WARNING
    assert msg.risk_level == 2
    assert isinstance(msg.alert_time, datetime)
