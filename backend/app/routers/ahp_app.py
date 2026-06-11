"""文物脆弱性评分 FastAPI 子应用"""
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, HTTPException, Depends

from app.config import get_settings
from app.services.orchestrator import MicroserviceOrchestrator
from app.routers.api import get_orchestrator
from app.algorithms.ahp_scorer import get_level_info

ahp_app = FastAPI(title="Vulnerability Scoring API", version="1.0.0")


def _enrich_score(score: Dict[str, Any]) -> Dict[str, Any]:
    """为评分结果添加颜色和中文名"""
    level_val, color, name = get_level_info(score.get("total_score", 50))
    score["level_color"] = color
    score["level_name"] = name
    return score


@ahp_app.get("/health")
async def health(settings=Depends(get_settings)):
    return {"status": "ok", "service": "vulnerability_scorer"}


@ahp_app.get("/scores")
async def list_vulnerability_scores(
    min_level: Optional[int] = None,
    limit: int = 300,
    orch: MicroserviceOrchestrator = Depends(get_orchestrator),
):
    """获取脆弱性评分列表"""
    scores = orch.ahp_scorer.get_scores(min_level=min_level, limit=limit)
    return [_enrich_score(s) for s in scores]


@ahp_app.get("/{artifact_id}")
async def get_single_vulnerability(
    artifact_id: str,
    orch: MicroserviceOrchestrator = Depends(get_orchestrator),
):
    """获取单个器物脆弱性详情（含保护建议）"""
    result = orch.ahp_scorer.get_score(artifact_id)
    if result is None:
        raise HTTPException(404, f"No vulnerability score for artifact {artifact_id}")
    return _enrich_score(result)


@ahp_app.get("/heatmap")
async def vulnerability_heatmap(
    grid_size: int = 40,
    orch: MicroserviceOrchestrator = Depends(get_orchestrator),
):
    """获取展厅脆弱性热力图数据"""
    return orch.ahp_scorer.get_heatmap_data(grid_size=grid_size)


@ahp_app.get("/stats")
async def vulnerability_stats(orch: MicroserviceOrchestrator = Depends(get_orchestrator)):
    """脆弱性统计概览"""
    stats = orch.ahp_scorer.get_stats()
    for s in stats.get("distribution", []):
        s["color"] = s.get("color", "#888888")
    return stats
