"""遗传算法喷涂路径规划 FastAPI 子应用"""
from typing import Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Depends

from app.config import get_settings
from app.services.orchestrator import MicroserviceOrchestrator
from app.routers.api import get_orchestrator

ga_app = FastAPI(title="GA Spray Path Planner API", version="1.0.0")


@ga_app.get("/health")
async def health(settings=Depends(get_settings)):
    return {"status": "ok", "service": "ga_spray_planner"}


@ga_app.post("/plan/{artifact_id}")
async def trigger_spray_plan(
    artifact_id: str,
    payload: Optional[Dict[str, Any]] = None,
    orch: MicroserviceOrchestrator = Depends(get_orchestrator),
):
    """触发单个器物的喷涂路径规划（支持进程池异步）"""
    generations = (payload or {}).get("generations", 60)
    population_size = (payload or {}).get("population_size", 50)
    result = await orch.ga_planner.plan_async(
        artifact_id=artifact_id,
        generations=generations,
        population_size=population_size,
    )
    if result is None:
        raise HTTPException(500, f"Spray planning failed for {artifact_id}")
    return result


@ga_app.get("/plans")
async def list_spray_plans(
    artifact_id: Optional[str] = None,
    limit: int = 100,
    orch: MicroserviceOrchestrator = Depends(get_orchestrator),
):
    """获取喷涂路径规划结果列表"""
    return orch.ga_planner.get_all_plans(artifact_id=artifact_id, limit=limit)


@ga_app.get("/plan/{artifact_id}")
async def get_single_spray_plan(
    artifact_id: str,
    orch: MicroserviceOrchestrator = Depends(get_orchestrator),
):
    """获取单个器物的喷涂路径规划（含轨迹）"""
    result = orch.ga_planner.get_plan(artifact_id)
    if result is None:
        raise HTTPException(404, f"No spray plan for artifact {artifact_id}")
    return result


@ga_app.get("/stats")
async def spray_plan_stats(orch: MicroserviceOrchestrator = Depends(get_orchestrator)):
    """喷涂规划统计"""
    return orch.ga_planner.get_stats()
