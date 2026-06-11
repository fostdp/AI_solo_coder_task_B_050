"""缓蚀剂残留寿命预测 FastAPI 子应用"""
from typing import Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Depends

from app.config import get_settings
from app.services.orchestrator import MicroserviceOrchestrator
from app.routers.api import get_orchestrator
from app.algorithms.life_predictor import (
    get_life_status_chinese,
    get_life_status_color,
)

life_app = FastAPI(title="Inhibitor Lifetime Prediction API", version="1.0.0")


@life_app.get("/health")
async def health(settings=Depends(get_settings)):
    return {"status": "ok", "service": "lifetime_predictor"}


@life_app.get("/results")
async def list_lifetime_results(
    artifact_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 200,
    orch: MicroserviceOrchestrator = Depends(get_orchestrator),
):
    """获取所有器物寿命预测结果"""
    return orch.life_predictor.get_all_results(
        artifact_id=artifact_id, status=status, limit=limit
    )


@life_app.get("/{artifact_id}")
async def get_single_lifetime(
    artifact_id: str,
    orch: MicroserviceOrchestrator = Depends(get_orchestrator),
):
    """获取单个器物寿命预测（带倒计时）"""
    result = orch.life_predictor.get_result(artifact_id)
    if result is None:
        raise HTTPException(404, f"No lifetime prediction for artifact {artifact_id}")
    pred, remaining = result
    return {
        "artifact_id": artifact_id,
        "inhibitor_type": pred.inhibitor_type.value,
        "remaining_days": pred.remaining_days,
        "remaining_seconds": remaining,
        "countdown_days": int(pred.remaining_days),
        "countdown_hours": int((pred.remaining_days % 1) * 24),
        "effectiveness": pred.effectiveness,
        "degradation_rate": pred.degradation_rate,
        "status": pred.status.value,
        "status_name": get_life_status_chinese(pred.status),
        "status_color": get_life_status_color(pred.status),
        "need_respray": pred.need_respray,
        "average_temp_7d": pred.average_temp_7d,
        "average_rh_7d": pred.average_rh_7d,
        "last_spray_date": pred.last_spray_date,
        "prediction_time": pred.prediction_time,
    }


@life_app.get("/stats")
async def lifetime_stats(orch: MicroserviceOrchestrator = Depends(get_orchestrator)):
    """寿命统计概览"""
    stats = orch.life_predictor.get_stats()
    for s in stats.get("by_status", []):
        s["status_name"] = get_life_status_chinese(s.get("status", "unknown"))
        s["status_color"] = get_life_status_color(s.get("status", "unknown"))
    return stats
