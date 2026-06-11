"""
告警推送模块
支持企业微信Webhook和短信双通道推送
"""

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum
import httpx

from ..config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class AlertType(str, Enum):
    RN_LOW = "Rn_low"
    CL_HIGH = "Cl_high"
    SO2_HIGH = "SO2_high"
    TEMP_HIGH = "Temp_high"
    HUMIDITY_HIGH = "Humidity_high"
    RUST_PREDICTION = "Rust_prediction"
    RUST_ERUPTION = "Rust_eruption"
    SPRAY_TASK = "Spray_task"


class AlertSeverity(int, Enum):
    INFO = 1
    WARNING = 2
    CRITICAL = 3
    EMERGENCY = 4


ALERT_TEMPLATES = {
    AlertType.RN_LOW: {
        "cn_name": "噪声电阻过低",
        "description": "电化学噪声电阻Rn低于阈值，疑似发生活性溶解",
        "default_severity": AlertSeverity.WARNING
    },
    AlertType.CL_HIGH: {
        "cn_name": "Cl⁻浓度超标",
        "description": "氯离子浓度超过安全阈值，粉状锈诱发风险升高",
        "default_severity": AlertSeverity.CRITICAL
    },
    AlertType.SO2_HIGH: {
        "cn_name": "SO₂浓度超标",
        "description": "二氧化硫浓度超标，加速青铜基体腐蚀",
        "default_severity": AlertSeverity.WARNING
    },
    AlertType.TEMP_HIGH: {
        "cn_name": "温度过高",
        "description": "展柜温度超出文物保存最佳范围",
        "default_severity": AlertSeverity.INFO
    },
    AlertType.HUMIDITY_HIGH: {
        "cn_name": "湿度过高",
        "description": "展柜相对湿度过高，易引发青铜器病害",
        "default_severity": AlertSeverity.WARNING
    },
    AlertType.RUST_PREDICTION: {
        "cn_name": "粉状锈爆发预警",
        "description": "基于AI模型预测，该器物近期存在粉状锈爆发高风险",
        "default_severity": AlertSeverity.CRITICAL
    },
    AlertType.RUST_ERUPTION: {
        "cn_name": "粉状锈爆发确认",
        "description": "视频显微镜已确认粉状锈爆发，需立即处理",
        "default_severity": AlertSeverity.EMERGENCY
    },
    AlertType.SPRAY_TASK: {
        "cn_name": "缓蚀剂喷涂任务通知",
        "description": "缓蚀剂智能喷涂系统已生成任务方案",
        "default_severity": AlertSeverity.INFO
    }
}


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
    suggestion: Optional[str] = None


class AlertDispatcher:
    def __init__(self):
        self.wecom_webhook = settings.WECOM_WEBHOOK_URL
        self.sms_api_url = settings.SMS_API_URL
        self.sms_api_key = settings.SMS_API_KEY
        self.sms_sender = settings.SMS_SENDER
        self.rate_limit = {}
        self.min_interval_seconds = 300

    async def dispatch(self, alert: AlertMessage) -> Dict[str, bool]:
        results = {"wecom": False, "sms": False}
        key = f"{alert.artifact_id}_{alert.alert_type.value}"
        now = time.time()

        if key in self.rate_limit:
            if now - self.rate_limit[key] < self.min_interval_seconds:
                logger.info(f"Alert {key} rate-limited, skipping push")
                return results

        self.rate_limit[key] = now

        tasks = []
        if self.wecom_webhook:
            tasks.append(asyncio.create_task(self._send_wecom(alert)))
        else:
            logger.warning("WeCom webhook not configured, simulating push")
            tasks.append(asyncio.create_task(self._simulate_wecom(alert)))

        if alert.severity.value >= AlertSeverity.CRITICAL.value:
            if self.sms_api_url and self.sms_api_key:
                tasks.append(asyncio.create_task(self._send_sms(alert)))
            else:
                logger.warning("SMS API not configured, simulating SMS push")
                tasks.append(asyncio.create_task(self._simulate_sms(alert)))

        done, pending = await asyncio.wait(tasks, timeout=10.0)
        for t in pending:
            t.cancel()

        for t in done:
            try:
                channel, ok = await t
                results[channel] = ok
            except Exception as e:
                logger.error(f"Alert push task failed: {e}")

        logger.info(
            f"Alert dispatched: {alert.alert_type.value} for "
            f"{alert.artifact_id}, results={results}"
        )
        return results

    def _build_wecom_message(self, alert: AlertMessage) -> Dict:
        severity_icons = {
            1: "ℹ️",
            2: "⚠️",
            3: "🔴",
            4: "🚨"
        }
        severity_colors = {
            1: "info",
            2: "warning",
            3: "comment",
            4: "comment"
        }

        tpl = ALERT_TEMPLATES.get(alert.alert_type, {})
        cn_name = tpl.get("cn_name", alert.alert_type.value)
        icon = severity_icons.get(alert.severity.value, "ℹ️")

        content_lines = [
            f"{icon} **青铜器粉状锈监测告警**",
            "",
            f"> **告警类型**: {cn_name}",
            f"> **告警级别**: {alert.severity.name}",
            f"> **器物编号**: {alert.artifact_id}",
            f"> **器物名称**: {alert.artifact_name}",
            f"> **告警时间**: {alert.alert_time.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            f"**指标详情**:",
            f"- 阈值: {alert.threshold_value} {alert.unit}",
            f"- 当前值: **{alert.actual_value} {alert.unit}**",
            f"- 偏离度: {abs(alert.actual_value - alert.threshold_value) / max(alert.threshold_value, 1e-6) * 100:.1f}%",
            "",
            f"**描述**: {alert.message}",
        ]

        if alert.risk_level:
            risk_text = ["低", "中", "高", "极高"][min(alert.risk_level - 1, 3)]
            content_lines.append(f"**风险等级**: {risk_text}")

        if alert.suggestion:
            content_lines.append("")
            content_lines.append(f"**处置建议**: {alert.suggestion}")

        content_lines.append("")
        content_lines.append(f"*来自青铜器粉状锈智能预警系统*")

        return {
            "msgtype": "markdown",
            "markdown": {
                "content": "\n".join(content_lines)
            }
        }

    async def _send_wecom(self, alert: AlertMessage) -> tuple:
        payload = self._build_wecom_message(alert)
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(self.wecom_webhook, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("errcode", -1) == 0:
                        return ("wecom", True)
                    logger.warning(f"WeCom API error: {data}")
                else:
                    logger.warning(f"WeCom HTTP {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.error(f"WeCom send exception: {e}")
        return ("wecom", False)

    async def _simulate_wecom(self, alert: AlertMessage) -> tuple:
        payload = self._build_wecom_message(alert)
        msg = payload.get("markdown", {}).get("content", "")
        lines = msg.split("\n")[:5]
        logger.info(
            f"[SIMULATED WeCom] Pushed alert {alert.alert_id}: "
            f"{' | '.join(l.strip('> ').strip() for l in lines if l.strip())}"
        )
        await asyncio.sleep(0.1)
        return ("wecom", True)

    def _build_sms_text(self, alert: AlertMessage) -> str:
        tpl = ALERT_TEMPLATES.get(alert.alert_type, {})
        cn_name = tpl.get("cn_name", alert.alert_type.value)
        text = (
            f"【青铜器预警】{alert.artifact_id}-{alert.artifact_name} "
            f"{cn_name}: {alert.actual_value}{alert.unit} "
            f"(阈值{alert.threshold_value})。"
        )
        if alert.severity.value >= AlertSeverity.CRITICAL.value:
            text += "请立即处理！"
        if len(text) > 70:
            text = text[:67] + "..."
        return text

    async def _send_sms(self, alert: AlertMessage) -> tuple:
        payload = {
            "apikey": self.sms_api_key,
            "sender": self.sms_sender,
            "content": self._build_sms_text(alert),
            "artifact_id": alert.artifact_id,
            "alert_id": alert.alert_id,
            "severity": alert.severity.value
        }
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(self.sms_api_url, json=payload)
                if resp.status_code == 200:
                    return ("sms", True)
        except Exception as e:
            logger.error(f"SMS send exception: {e}")
        return ("sms", False)

    async def _simulate_sms(self, alert: AlertMessage) -> tuple:
        text = self._build_sms_text(alert)
        logger.info(
            f"[SIMULATED SMS] Sent alert {alert.alert_id} "
            f"(severity={alert.severity.name}): {text}"
        )
        await asyncio.sleep(0.1)
        return ("sms", True)

    def build_alert_suggestion(
        self,
        alert_type: AlertType,
        severity: AlertSeverity,
        actual_value: float,
        threshold_value: float
    ) -> str:
        suggestions = {
            AlertType.RN_LOW: [
                "加强实时监测，缩短检测周期",
                "增加视频显微镜巡检频次",
                "评估是否启动预防性缓蚀剂喷涂",
                "检查展柜密封性和内部微环境"
            ],
            AlertType.CL_HIGH: [
                "立即检查展柜密封性，排查外部污染源",
                "启动展柜内部空气循环净化装置",
                "放置活性炭或离子交换树脂吸附",
                "评估是否启动预防性喷涂BTA缓蚀剂"
            ],
            AlertType.SO2_HIGH: [
                "检查博物馆新风系统过滤装置",
                "展柜内放置脱硫吸附剂",
                "减少开启展柜频率"
            ],
            AlertType.TEMP_HIGH: [
                "检查展柜温湿度控制系统",
                "确认空调机组运行状态",
                "排查是否有局部热源影响"
            ],
            AlertType.HUMIDITY_HIGH: [
                "启动展柜除湿装置",
                "检查密封胶条完整性",
                "放置干燥剂辅助控湿"
            ],
            AlertType.RUST_PREDICTION: [
                "立即安排文保人员现场核查",
                "使用视频显微镜逐点扫描可疑区域",
                "启动智能喷涂系统执行预防性处理",
                "上报文保部门制定专项保护方案"
            ],
            AlertType.RUST_ERUPTION: [
                "紧急启动应急预案，隔离该展柜区域",
                "立即执行缓蚀剂紧急喷涂",
                "联系文保专家现场会诊",
                "建立专项档案，启动持续监测"
            ],
            AlertType.SPRAY_TASK: [
                "审核喷涂方案参数是否合理",
                "确认缓蚀剂类型（BTA/AMT/MBO）选型",
                "安排现场操作安全防护"
            ]
        }

        list_sg = suggestions.get(alert_type, [])
        ratio = max(actual_value, 1e-6) / max(threshold_value, 1e-6)
        n = min(len(list_sg), max(1, int(severity.value)))
        if ratio > 2.0 and len(list_sg) > n:
            n = min(len(list_sg), n + 1)

        return "；".join(list_sg[:n])


dispatcher = AlertDispatcher()
