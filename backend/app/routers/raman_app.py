"""拉曼光谱识别 FastAPI 子应用"""
from typing import Dict, Any, Optional, List
from fastapi import FastAPI, HTTPException, Depends

from app.config import get_settings
from app.services.orchestrator import MicroserviceOrchestrator
from app.routers.api import get_orchestrator
from app.algorithms.raman_cnn import (
    get_raman_color,
    get_product_chinese_name,
)

raman_app = FastAPI(title="Raman Spectra Analysis API", version="1.0.0")


@raman_app.get("/health")
async def health(settings=Depends(get_settings)):
    return {"status": "ok", "service": "raman_analysis"}


@raman_app.post("/analyze")
async def raman_analyze(
    payload: Dict[str, Any],
    orch: MicroserviceOrchestrator = Depends(get_orchestrator),
):
    """异步分析拉曼光谱数据（ONNX Runtime线程池推理，不阻塞事件循环）"""
    result = await orch.raman.analyze_async(payload)
    if result is None:
        raise HTTPException(500, "Raman analysis failed")
    return {
        "artifact_id": result.artifact_id,
        "product_type": result.product_type.value,
        "product_name": get_product_chinese_name(result.product_type),
        "product_color": get_raman_color(result.product_type),
        "confidence": result.confidence,
        "probabilities": result.probabilities,
        "peak_positions": result.peak_positions,
        "prediction_time": result.prediction_time,
    }


@raman_app.post("/analyze/sync")
async def raman_analyze_sync(
    payload: Dict[str, Any],
    orch: MicroserviceOrchestrator = Depends(get_orchestrator),
):
    """同步分析拉曼光谱（兼容性接口）"""
    result = orch.raman.analyze_sync(payload)
    if result is None:
        raise HTTPException(500, "Raman analysis failed")
    return {
        "artifact_id": result.artifact_id,
        "product_type": result.product_type.value,
        "product_name": get_product_chinese_name(result.product_type),
        "product_color": get_raman_color(result.product_type),
        "confidence": result.confidence,
        "probabilities": result.probabilities,
        "peak_positions": result.peak_positions,
        "prediction_time": result.prediction_time,
    }


@raman_app.get("/results")
async def list_raman_results(
    artifact_id: Optional[str] = None,
    limit: int = 50,
    orch: MicroserviceOrchestrator = Depends(get_orchestrator),
):
    """获取拉曼识别结果（从内存缓存）"""
    return orch.raman.get_results(artifact_id=artifact_id, limit=limit)


@raman_app.get("/stats")
async def raman_stats(orch: MicroserviceOrchestrator = Depends(get_orchestrator)):
    """获取拉曼分析统计"""
    return orch.raman.get_stats()
