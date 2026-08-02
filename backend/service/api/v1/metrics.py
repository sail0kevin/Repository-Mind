"""在线检索质量指标接口。"""
from __future__ import annotations

from fastapi import APIRouter, Query

from service.storage.retrieval_metrics_store import get_retrieval_metrics

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
def metrics(
    days: int = Query(default=7, ge=1, le=30),
    repo_id: str | None = Query(default=None, min_length=1),
) -> dict:
    return get_retrieval_metrics(days=days, repo_id=repo_id)
