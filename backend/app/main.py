import sys
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
import asyncio
import json

from .config import get_settings
from .routers.api import router as api_router
from .routers.raman_app import raman_app
from .routers.life_app import life_app
from .routers.ahp_app import ahp_app
from .routers.ga_app import ga_app
from .mqtt_processor import data_processor

settings = get_settings()

try:
    from .observability import (
        setup_logging,
        create_prometheus_middleware,
        get_logger,
        set_service_health,
        ACTIVE_CONNECTIONS,
        ARTIFACTS_MONITORED,
    )
    setup_logging(
        log_dir=os.getenv("LOG_DIR", "/var/log/bronze-rust"),
        enable_json=os.getenv("ENVIRONMENT", "development") == "production",
    )
    logger = get_logger("bronze_app")
    OBSERVABILITY_ENABLED = True
except ImportError:
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    logger = logging.getLogger("bronze_app")
    OBSERVABILITY_ENABLED = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up Bronze Rust Monitor Application v3.0...")
    logger.info(f"App env: {settings.APP_ENV}, port: {settings.APP_PORT}")

    if OBSERVABILITY_ENABLED:
        set_service_health("backend", "startup", True)

    if data_processor.connect_and_subscribe():
        logger.info("MQTT processor connected and subscribing")
    else:
        logger.warning(
            "MQTT broker not available. Will still work via direct HTTP ingest. "
            "Start MQTT broker and mqtt_simulator.py for live data simulation."
        )

    app.state.mqtt_processor = data_processor

    if OBSERVABILITY_ENABLED:
        ARTIFACTS_MONITORED.labels(service="backend").set(0)
        set_service_health("backend", "mqtt", bool(data_processor.mqtt_client))

    yield

    logger.info("Shutting down application...")
    data_processor.disconnect()

    if OBSERVABILITY_ENABLED:
        set_service_health("backend", "shutdown", False)

    logger.info("Application shutdown complete.")


app = FastAPI(
    title="古代青铜器粉状锈爆发预警与缓蚀剂智能喷涂系统",
    description=(
        "基于电化学噪声时频特征（小波包分解）+随机森林/XGBoost融合的粉状锈爆发预测，"
        "结合CFD简化模型的缓蚀剂(BTA/AMT/MBO)雾化喷涂优化系统。"
        "传感器：30台电化学噪声+50台微环境+20台视频显微镜，每15分钟MQTT上报。"
        "微服务架构：mqtt_ingest→feature_extractor→predictor→optimizer→alert_ws，"
        "模块间通过Redis Stream通信。"
    ),
    version="3.0.0",
    lifespan=lifespan,
)

if OBSERVABILITY_ENABLED:
    create_prometheus_middleware(app, service_name="bronze_rust_backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)

# 新增模块：独立FastAPI子应用（v2架构）
app.mount("/api/v2/raman", raman_app)
app.mount("/api/v2/lifetime", life_app)
app.mount("/api/v2/vulnerability", ahp_app)
app.mount("/api/v2/ga-spray", ga_app)


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        if OBSERVABILITY_ENABLED:
            ACTIVE_CONNECTIONS.labels(service="backend").set(len(self.active_connections))
        logger.info(f"WebSocket client connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        if OBSERVABILITY_ENABLED:
            ACTIVE_CONNECTIONS.labels(service="backend").set(len(self.active_connections))
        logger.info(f"WebSocket client disconnected. Remaining: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        payload = json.dumps(message, ensure_ascii=False, default=str)
        dead = []
        for conn in self.active_connections:
            try:
                await conn.send_text(payload)
            except Exception:
                dead.append(conn)
        for d in dead:
            self.disconnect(d)


manager = ConnectionManager()


@app.websocket("/ws/realtime")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            if msg.get("type") == "ping":
                await websocket.send_json({"type": "pong", "ts": datetime.utcnow().isoformat()})
            elif msg.get("type") == "subscribe":
                aid = msg.get("artifact_id")
                realtime = data_processor.get_realtime_data(aid)
                await websocket.send_json({
                    "type": "realtime_update",
                    "data": realtime,
                    "ts": datetime.utcnow().isoformat(),
                })
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)


async def broadcast_loop():
    while True:
        try:
            data = data_processor.get_realtime_data()
            summary = {
                "type": "realtime_summary",
                "data_count": len(data),
                "updated_artifacts": list(data.keys())[:50],
                "sample": dict(list(data.items())[:5]),
                "ts": datetime.utcnow().isoformat(),
            }
            await manager.broadcast(summary)
        except Exception as e:
            logger.error(f"Broadcast error: {e}")
        await asyncio.sleep(30)


@app.on_event("startup")
async def schedule_broadcast():
    asyncio.create_task(broadcast_loop())


@app.get("/")
async def root():
    return {
        "name": "古代青铜器粉状锈爆发预警与缓蚀剂智能喷涂系统",
        "version": "3.0.0",
        "docs": "/docs",
        "endpoints": {
            "artifacts": "/api/artifacts",
            "realtime": "/api/artifacts/realtime/all",
            "statistics": "/api/statistics",
            "alerts": "/api/alerts",
            "predictions": "/api/artifacts/{{id}}/predictions",
            "risk_zones": "/api/artifacts/{{id}}/risk-zones",
            "spray_optimize": "/api/spray-tasks/optimize (POST)",
            "ingest": "/api/ingest/{{sensor_type}} (POST)",
            "websocket": "/ws/realtime",
            "metrics": "/metrics",
        },
    }


@app.get("/api/health")
async def health_check():
    mqtt_ok = bool(data_processor.mqtt_client)
    if OBSERVABILITY_ENABLED:
        set_service_health("backend", "mqtt", mqtt_ok)
    return {
        "status": "healthy" if mqtt_ok else "degraded",
        "version": "3.0.0",
        "mqtt_connected": mqtt_ok,
        "observability": OBSERVABILITY_ENABLED,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=settings.APP_ENV == "development",
        log_level="info",
    )
