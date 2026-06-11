"""
Alert & WebSocket Service (微服务5)
职责：
  1. 从 Redis Stream:alerts 消费告警消息
  2. 企业微信 + 短信双通道推送
  3. WebSocket 实时推送到前端
  4. 告警冷却、防抖动

数据流：Redis Stream:alerts -> 推送通道 -> WebSocket广播
"""

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Dict, Optional, List
from dataclasses import dataclass
from enum import Enum

from ..config import get_settings
from ..streams import RedisStreamManager, parse_stream_message

logger = logging.getLogger("alert_ws")
settings = get_settings()


class AlertType(str, Enum):
    RN_LOW = "rn_low"
    CL_HIGH = "cl_high"
    SO2_HIGH = "so2_high"
    TEMP_HIGH = "temp_high"
    HUMIDITY_HIGH = "humidity_high"
    RUST_ERUPTION = "rust_eruption"
    RUST_PREDICTION = "rust_prediction"


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


@dataclass
class AlertMessage:
    alert_id: int
    artifact_id: str
    artifact_name: str
    alert_type: AlertType
    severity: AlertSeverity
    threshold_value: float
    actual_value: float
    unit: str
    message: str
    alert_time: datetime
    risk_level: Optional[int] = None
    suggestion: str = ""


ALERT_TEMPLATES = {
    AlertType.RN_LOW: {
        "description": "电化学噪声电阻异常偏低",
        "suggestion": "建议立即检查文物表面状态，加强环境监测",
        "severity_default": AlertSeverity.WARNING
    },
    AlertType.CL_HIGH: {
        "description": "氯离子浓度超标",
        "suggestion": "建议开启除湿和空气净化系统",
        "severity_default": AlertSeverity.CRITICAL
    },
    AlertType.SO2_HIGH: {
        "description": "二氧化硫浓度超标",
        "suggestion": "建议检查通风系统，增加活性炭吸附",
        "severity_default": AlertSeverity.WARNING
    },
    AlertType.TEMP_HIGH: {
        "description": "环境温度偏高",
        "suggestion": "建议调节空调温度",
        "severity_default": AlertSeverity.INFO
    },
    AlertType.HUMIDITY_HIGH: {
        "description": "环境湿度偏高",
        "suggestion": "建议开启除湿设备",
        "severity_default": AlertSeverity.WARNING
    },
    AlertType.RUST_ERUPTION: {
        "description": "检测到粉状锈爆发",
        "suggestion": "紧急启动缓蚀剂喷涂预案，组织文物应急保护",
        "severity_default": AlertSeverity.EMERGENCY
    },
    AlertType.RUST_PREDICTION: {
        "description": "粉状锈爆发风险预警",
        "suggestion": "建议提前安排预防性喷涂",
        "severity_default": AlertSeverity.WARNING
    }
}


class AlertDispatcher:
    """告警推送器 - 企业微信 + 短信"""

    def __init__(self):
        self.wecom_url = settings.WECOM_WEBHOOK_URL
        self.sms_api_url = settings.SMS_API_URL
        self.sms_api_key = settings.SMS_API_KEY
        self.sms_sender = settings.SMS_SENDER

    async def dispatch(self, alert: AlertMessage) -> Dict:
        results = {}

        if self.wecom_url:
            try:
                results["wecom"] = await self._send_wecom(alert)
            except Exception as e:
                logger.error(f"WeCom send failed: {e}")
                results["wecom"] = False
        else:
            results["wecom"] = False

        if self.sms_api_url and self.sms_api_key:
            try:
                results["sms"] = await self._send_sms(alert)
            except Exception as e:
                logger.error(f"SMS send failed: {e}")
                results["sms"] = False
        else:
            results["sms"] = False

        return results

    async def _send_wecom(self, alert: AlertMessage) -> bool:
        import aiohttp
        title = f"【{alert.severity.value.upper()}】{alert.message}"
        text = (
            f"文物: {alert.artifact_name}\n"
            f"类型: {alert.alert_type.value}\n"
            f"告警值: {alert.actual_value:.3f}{alert.unit} (阈值: {alert.threshold_value})\n"
            f"建议: {alert.suggestion}\n"
            f"时间: {alert.alert_time:%Y-%m-%d %H:%M:%S}"
        )

        payload = {
            "msgtype": "text",
            "text": {"content": f"{title}\n\n{text}"}
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(self.wecom_url, json=payload) as resp:
                data = await resp.json()
                return data.get("errcode", -1) == 0

    async def _send_sms(self, alert: AlertMessage) -> bool:
        import aiohttp
        payload = {
            "api_key": self.sms_api_key,
            "sender": self.sms_sender,
            "mobile": "",
            "template": "rust_alert",
            "params": {
                "artifact": alert.artifact_name,
                "value": f"{alert.actual_value:.2f}",
                "threshold": f"{alert.threshold_value}"
            }
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(self.sms_api_url, json=payload) as resp:
                data = await resp.json()
                return data.get("code") == 0

    def build_alert_suggestion(
        self, alert_type: AlertType, severity: AlertSeverity,
        actual: float, threshold: float
    ) -> str:
        tpl = ALERT_TEMPLATES.get(alert_type, {})
        base = tpl.get("suggestion", "请检查相关系统")
        ratio = actual / threshold if threshold > 0 else 999
        if ratio > 2.0:
            return base + "（严重超标，建议立即处理"
        elif ratio > 1.5:
            return base + "（超标较多，建议尽快处理"
        return base


class WebSocketManager:
    """WebSocket 连接管理器"""

    def __init__(self):
        self.active_connections: list = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket):
        await websocket.accept()
        async with self._lock:
            self.active_connections.append(websocket)
        logger.info(f"WebSocket client connected. Total: {len(self.active_connections)}")

    async def disconnect(self, websocket):
        async with self._lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
        logger.info(f"WebSocket client disconnected. Remaining: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        payload = json.dumps(message, ensure_ascii=False, default=str)
        dead = []
        async with self._lock:
            for conn in list(self.active_connections):
                try:
                    await conn.send_text(payload)
                except Exception:
                    dead.append(conn)
            for d in dead:
                if d in self.active_connections:
                    self.active_connections.remove(d)

    async def broadcast_realtime(self, data: dict):
        await self.broadcast({
            "type": "realtime_update",
            "data": data,
            "ts": datetime.utcnow().isoformat()
        })

    async def broadcast_alert(self, alert: dict):
        await self.broadcast({
            "type": "alert",
            "alert": alert,
            "ts": datetime.utcnow().isoformat()
        })

    def connection_count(self) -> int:
        return len(self.active_connections)


class AlertWSService:
    """告警与WebSocket微服务"""

    def __init__(
        self,
        stream_manager: Optional[RedisStreamManager] = None,
        ws_manager: Optional[WebSocketManager] = None
    ):
        self.stream_mgr = stream_manager
        self.ws_mgr = ws_manager or WebSocketManager()
        self.dispatcher = AlertDispatcher()

        self._alert_stream = settings.REDIS_STREAM_ALERTS
        self._group = settings.REDIS_GROUP_ALERT
        self._consumer_name = f"alert_ws_{id(self)}"

        self.alert_cooldown: Dict[str, float] = {}
        self._cooldown_seconds = settings.ALERT_COOLDOWN

        self._running = False
        self._stats = {
            "alerts_received": 0,
            "alerts_pushed": 0,
            "alerts_cooldown_skipped": 0,
            "ws_broadcasts": 0,
            "failed": 0
        }

    async def start(self):
        if self.stream_mgr:
            await self.stream_mgr.ensure_stream(self._alert_stream)
            await self.stream_mgr.ensure_group(self._alert_stream, self._group)
        self._running = True
        logger.info("Alert & WebSocket service started")

    async def stop(self):
        self._running = False
        logger.info("Alert & WebSocket service stopped")

    async def run_loop(self):
        await self.start()
        while self._running:
            try:
                if not self.stream_mgr:
                    messages = await self.stream_mgr.consume_group(
                        self._alert_stream,
                        self._group,
                        self._consumer_name,
                        count=10,
                        block_ms=2000
                    )

                    for stream_name, stream_msgs in messages:
                        for msg in stream_msgs:
                            try:
                                parsed = parse_stream_message(msg)
                                await self._process_alert(parsed)
                                await self.stream_mgr.ack(
                                    self._alert_stream, self._group, parsed["_id"]
                                )
                                self._stats["alerts_received"] += 1
                            except Exception as e:
                                self._stats["failed"] += 1
                                logger.exception(f"Alert processing failed: {e}")

                    if not messages:
                        await asyncio.sleep(0.5)
                else:
                    await asyncio.sleep(1)

            except Exception as e:
                logger.exception(f"AlertWS loop error: {e}")
                await asyncio.sleep(1)

    async def _process_alert(self, msg: Dict):
        artifact_id = msg.get("artifact_id", "")
        alert_type_str = msg.get("alert_type", "unknown")

        key = f"{artifact_id}_{alert_type_str}"
        now = time.time()
        last = self.alert_cooldown.get(key, 0)

        if now - last < self._cooldown_seconds:
            self._stats["alerts_cooldown_skipped"] += 1
            logger.debug(f"Alert cooldown skipped for {key}")
            return

        self.alert_cooldown[key] = now

        try:
            alert_type = AlertType(alert_type_str) if alert_type_str in [e.value for e in AlertType] else AlertType.RN_LOW
        except ValueError:
            alert_type = AlertType.RN_LOW

        tpl = ALERT_TEMPLATES.get(alert_type, {})
        suggestion = self.dispatcher.build_alert_suggestion(
            alert_type,
            AlertSeverity(msg.get("severity", "warning")),
            float(msg.get("actual_value", 0)),
            float(msg.get("threshold_value", 0))
        )

        alert_msg = AlertMessage(
            alert_id=int(msg.get("alert_id", 0)),
            artifact_id=artifact_id,
            artifact_name=msg.get("artifact_name", artifact_id),
            alert_type=alert_type,
            severity=AlertSeverity(msg.get("severity", "warning")),
            threshold_value=float(msg.get("threshold_value", 0)),
            actual_value=float(msg.get("actual_value", 0)),
            unit=msg.get("unit", ""),
            message=msg.get("message", tpl.get("description", "")),
            alert_time=datetime.fromisoformat(msg.get("alert_time", datetime.utcnow().isoformat())) if isinstance(msg.get("alert_time"), str) else datetime.utcnow(),
            risk_level=msg.get("risk_level"),
            suggestion=suggestion
        )

        push_result = await self.dispatcher.dispatch(alert_msg)
        self._stats["alerts_pushed"] += 1

        await self.ws_mgr.broadcast_alert({
            "alert_id": alert_msg.alert_id,
            "artifact_id": alert_msg.artifact_id,
            "artifact_name": alert_msg.artifact_name,
            "alert_type": alert_msg.alert_type.value,
            "severity": alert_msg.severity.value,
            "message": alert_msg.message,
            "actual_value": alert_msg.actual_value,
            "threshold_value": alert_msg.threshold_value,
            "unit": alert_msg.unit,
            "suggestion": alert_msg.suggestion,
            "risk_level": alert_msg.risk_level,
            "alert_time": alert_msg.alert_time.isoformat()
        })
        self._stats["ws_broadcasts"] += 1

        logger.warning(
            f"ALERT [{alert_type.value} S{alert_msg.severity.value} "
            f"{artifact_id}: {alert_msg.actual_value:.3f}{alert_msg.unit} "
            f"-> pushed: {push_result}"
        )

    async def trigger_alert_direct(self, alert_data: Dict):
        """直接触发告警（兼容 HTTP API 调用）"""
        if self.stream_mgr:
            await self.stream_mgr.publish(self._alert_stream, alert_data)
        else:
            await self._process_alert(alert_data)

    def get_stats(self) -> Dict:
        return {
            **self._stats,
            "is_running": self._running,
            "ws_connections": self.ws_mgr.connection_count(),
            "cooldown_seconds": self._cooldown_seconds
        }
