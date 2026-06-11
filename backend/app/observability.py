"""
日志与监控模块
- Loguru 结构化日志
- Prometheus 指标导出
"""

import os
import sys
import time
import json
import socket
import logging
from typing import Any, Dict, Optional
from datetime import datetime, timezone

from loguru import logger
from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    Summary,
    CollectorRegistry,
    generate_latest,
    CONTENT_TYPE_LATEST,
)

APP_NAME = "bronze_rust_alert"
HOSTNAME = socket.gethostname()
ENV = os.getenv("ENVIRONMENT", "development")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# ========================================
# Prometheus 指标定义
# ========================================

REGISTRY = CollectorRegistry(auto_describe=True)

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status_code", "service"],
    registry=REGISTRY,
)

REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint", "service"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=REGISTRY,
)

MQTT_MESSAGES = Counter(
    "mqtt_messages_total",
    "Total MQTT messages received",
    ["topic", "sensor_type", "status"],
    registry=REGISTRY,
)

STREAM_MESSAGES = Counter(
    "stream_messages_total",
    "Total Redis Stream messages processed",
    ["stream_name", "service", "status"],
    registry=REGISTRY,
)

PREDICTIONS_TOTAL = Counter(
    "predictions_total",
    "Total model predictions",
    ["artifact_id", "risk_level", "model_version"],
    registry=REGISTRY,
)

ALERTS_TOTAL = Counter(
    "alerts_total",
    "Total alerts generated",
    ["artifact_id", "alert_type", "severity", "channel"],
    registry=REGISTRY,
)

SPRAY_OPTIMIZATIONS = Counter(
    "spray_optimizations_total",
    "Total spray optimizations performed",
    ["artifact_id", "inhibitor_type"],
    registry=REGISTRY,
)

ACTIVE_CONNECTIONS = Gauge(
    "websocket_active_connections",
    "Active WebSocket connections",
    ["service"],
    registry=REGISTRY,
)

ARTIFACTS_MONITORED = Gauge(
    "artifacts_monitored_count",
    "Number of artifacts currently monitored",
    ["service"],
    registry=REGISTRY,
)

SERVICE_HEALTH = Gauge(
    "service_health_status",
    "Service health status (1=healthy, 0=unhealthy)",
    ["service", "component"],
    registry=REGISTRY,
)

FEATURE_EXTRACTION_TIME = Summary(
    "feature_extraction_duration_seconds",
    "Time spent extracting wavelet features",
    ["artifact_id"],
    registry=REGISTRY,
)

INFERENCE_TIME = Summary(
    "model_inference_duration_seconds",
    "Time spent in model inference",
    ["artifact_id", "model_type"],
    registry=REGISTRY,
)

ERROR_COUNT = Counter(
    "errors_total",
    "Total errors by component",
    ["component", "error_type"],
    registry=REGISTRY,
)


def record_error(component: str, error_type: str):
    ERROR_COUNT.labels(component=component, error_type=error_type).inc()


def record_mqtt_message(topic: str, sensor_type: str, status: str = "success"):
    MQTT_MESSAGES.labels(topic=topic, sensor_type=sensor_type, status=status).inc()


def record_stream_message(stream_name: str, service: str, status: str = "success"):
    STREAM_MESSAGES.labels(
        stream_name=stream_name, service=service, status=status
    ).inc()


def record_prediction(artifact_id: str, risk_level: int, model_version: str):
    PREDICTIONS_TOTAL.labels(
        artifact_id=artifact_id,
        risk_level=str(risk_level),
        model_version=model_version,
    ).inc()


def record_alert(artifact_id: str, alert_type: str, severity: str, channel: str):
    ALERTS_TOTAL.labels(
        artifact_id=artifact_id,
        alert_type=alert_type,
        severity=severity,
        channel=channel,
    ).inc()


def set_service_health(service: str, component: str, healthy: bool):
    SERVICE_HEALTH.labels(service=service, component=component).set(1 if healthy else 0)


def get_metrics_response() -> bytes:
    return generate_latest(REGISTRY)


# ========================================
# Loguru 配置
# ========================================

class JSONFormatter:
    """自定义 JSON 日志格式化器"""

    @staticmethod
    def format(record: Dict[str, Any]) -> str:
        log_record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record["level"].name,
            "logger": record["name"],
            "message": record["message"],
            "service": APP_NAME,
            "hostname": HOSTNAME,
            "env": ENV,
            "module": record.get("module"),
            "function": record.get("function"),
            "line": record.get("line"),
            "process_id": record.get("process").id if record.get("process") else None,
            "thread_id": record.get("thread").id if record.get("thread") else None,
        }

        if record["extra"]:
            log_record["context"] = record["extra"]

        if record["exception"]:
            log_record["exception"] = str(record["exception"])

        return json.dumps(log_record, ensure_ascii=False) + "\n"


def setup_logging(
    log_dir: str = "/var/log/bronze-rust",
    log_level: Optional[str] = None,
    enable_json: bool = True,
    enable_console: bool = True,
    max_bytes: int = 50 * 1024 * 1024,
    backup_count: int = 10,
):
    """
    配置全局日志系统

    Args:
        log_dir: 日志目录
        log_level: 日志级别，默认取环境变量 LOG_LEVEL
        enable_json: 是否输出 JSON 格式日志到文件
        enable_console: 是否输出到控制台
        max_bytes: 单个日志文件最大大小 (50MB)
        backup_count: 最大保留文件数
    """
    level = (log_level or LOG_LEVEL).upper()

    logger.remove()

    if enable_console:
        console_fmt = (
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        )
        logger.add(
            sys.stdout,
            level=level,
            format=console_fmt,
            colorize=True,
            enqueue=True,
            backtrace=True,
            diagnose=ENV != "production",
        )

    if enable_json:
        os.makedirs(log_dir, exist_ok=True)

        info_log = os.path.join(log_dir, "app.log")
        logger.add(
            info_log,
            level=level,
            format=JSONFormatter.format,
            rotation=max_bytes,
            retention=backup_count,
            compression="gzip",
            enqueue=True,
            backtrace=True,
            serialize=False,
        )

        error_log = os.path.join(log_dir, "error.log")
        logger.add(
            error_log,
            level="ERROR",
            format=JSONFormatter.format,
            rotation=max_bytes,
            retention=backup_count * 2,
            compression="gzip",
            enqueue=True,
            backtrace=True,
            serialize=False,
        )

    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

    for log_name in ["uvicorn", "fastapi", "uvicorn.access", "asyncio"]:
        lgr = logging.getLogger(log_name)
        lgr.handlers = [InterceptHandler()]
        lgr.setLevel(level if level in ("INFO", "WARNING", "ERROR") else "INFO")

    logger.info(
        f"Logging initialized: level={level}, json={enable_json}, "
        f"console={enable_console}, log_dir={log_dir}"
    )
    return logger


class InterceptHandler(logging.Handler):
    """将标准 logging 转发到 loguru"""

    def emit(self, record: logging.LogRecord):
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = sys._getframe(6), 6
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def get_logger(name: Optional[str] = None) -> logger:
    """获取带上下文的 logger 实例"""
    if name:
        return logger.bind(module=name)
    return logger


# ========================================
# FastAPI 中间件
# ========================================

def create_prometheus_middleware(app, service_name: str = APP_NAME):
    """为 FastAPI 应用注册 Prometheus 指标中间件"""

    from fastapi import Request, Response
    from starlette.middleware.base import BaseHTTPMiddleware

    class PrometheusMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            start_time = time.perf_counter()
            method = request.method
            endpoint = request.url.path

            try:
                response: Response = await call_next(request)
                status_code = response.status_code

                latency = time.perf_counter() - start_time
                REQUEST_LATENCY.labels(
                    method=method, endpoint=endpoint, service=service_name
                ).observe(latency)
                REQUEST_COUNT.labels(
                    method=method,
                    endpoint=endpoint,
                    status_code=str(status_code),
                    service=service_name,
                ).inc()

                return response

            except Exception as e:
                latency = time.perf_counter() - start_time
                REQUEST_LATENCY.labels(
                    method=method, endpoint=endpoint, service=service_name
                ).observe(latency)
                REQUEST_COUNT.labels(
                    method=method,
                    endpoint=endpoint,
                    status_code="500",
                    service=service_name,
                ).inc()
                record_error("http_middleware", type(e).__name__)
                raise

    app.add_middleware(PrometheusMiddleware)

    @app.get("/metrics", include_in_schema=False)
    async def metrics():
        return Response(
            content=get_metrics_response(),
            media_type=CONTENT_TYPE_LATEST,
            headers={"Cache-Control": "no-cache"},
        )

    return app


__all__ = [
    "setup_logging",
    "get_logger",
    "create_prometheus_middleware",
    "get_metrics_response",
    "record_error",
    "record_mqtt_message",
    "record_stream_message",
    "record_prediction",
    "record_alert",
    "set_service_health",
    "ACTIVE_CONNECTIONS",
    "ARTIFACTS_MONITORED",
    "SERVICE_HEALTH",
    "FEATURE_EXTRACTION_TIME",
    "INFERENCE_TIME",
    "REGISTRY",
]
