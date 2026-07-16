"""代码图谱查询 API；所有产品查询统一限制到 succeeded 快照。"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from service.api.v1.repos import resolve_product_snapshot
from service.core.codegraph.store import (
    get_call_chain,
    get_class_relations,
    get_graph_stats,
    get_important_nodes,
    search_graph_nodes,
)
from service.storage.models import (
    CodeGraphCallChainResponse,
    CodeGraphClassResponse,
    CodeGraphImportantResponse,
    CodeGraphSearchRequest,
    CodeGraphSearchResponse,
    CodeGraphStatsResponse,
)
from service.storage.repository_store import get_repo_record

router = APIRouter(tags=["code-graph"])


def _require_repo(repo_id: str) -> None:
    """统一检查仓库是否存在。"""
    if get_repo_record(repo_id) is None:
        raise HTTPException(status_code=404, detail="没有找到指定仓库。")


def _resolve_snapshot(repo_id: str, snapshot_id: str | None) -> str:
    """复用仓库 API 的 succeeded/404/409 语义。"""
    return resolve_product_snapshot(repo_id, snapshot_id)["id"]


def _graph_stats(repo_id: str, snapshot_id: str) -> dict:
    """为旧查询响应补回统计字段，同时声明实际读取的快照。"""
    return {**get_graph_stats(repo_id, snapshot_id), "snapshot_id": snapshot_id}


@router.get("/api/v1/code-graph/{repo_id}/stats", response_model=CodeGraphStatsResponse)
def code_graph_stats(repo_id: str, snapshot_id: str | None = None) -> dict:
    _require_repo(repo_id)
    selected = _resolve_snapshot(repo_id, snapshot_id)
    return _graph_stats(repo_id, selected)


@router.get("/api/v1/code-graph/{repo_id}/important", response_model=CodeGraphImportantResponse)
def code_graph_important(repo_id: str, limit: int = Query(default=20, ge=1, le=100), snapshot_id: str | None = None) -> dict:
    _require_repo(repo_id)
    selected = _resolve_snapshot(repo_id, snapshot_id)
    nodes = get_important_nodes(repo_id, limit, selected)
    return {
        "repo_id": repo_id,
        "snapshot_id": selected,
        "nodes": nodes,
        # results/functions 是旧桌面端读取列表时识别的历史语义字段。
        "results": nodes,
        "functions": nodes,
        "stats": _graph_stats(repo_id, selected),
    }


def _search_response(repo_id: str, query: str, limit: int, snapshot_id: str) -> dict:
    """统一新旧搜索响应，保留原 matches/stats 及历史列表别名。"""
    matches = search_graph_nodes(repo_id, query, limit, snapshot_id=snapshot_id) if query else []
    return {
        "repo_id": repo_id,
        "snapshot_id": snapshot_id,
        "query": query,
        "matches": matches,
        "results": matches,
        "functions": matches,
        "stats": _graph_stats(repo_id, snapshot_id),
    }


@router.get("/api/v1/code-graph/{repo_id}/search", response_model=CodeGraphSearchResponse)
def code_graph_search_get(repo_id: str, q: str = Query(min_length=1), limit: int = Query(default=20, ge=1, le=100),
                          snapshot_id: str | None = None) -> dict:
    _require_repo(repo_id)
    selected = _resolve_snapshot(repo_id, snapshot_id)
    return _search_response(repo_id, q, limit, selected)


@router.post("/api/v1/code-graph/{repo_id}/search", response_model=CodeGraphSearchResponse, include_in_schema=False)
def code_graph_search_post(repo_id: str, payload: CodeGraphSearchRequest, snapshot_id: str | None = None) -> dict:
    """兼容旧 POST：空或不含查询词的字典仍返回空 matches 和 stats。"""
    _require_repo(repo_id)
    query = (payload.query or payload.q or "").strip()
    selected = _resolve_snapshot(repo_id, snapshot_id)
    return _search_response(repo_id, query, payload.limit, selected)


@router.get("/api/v1/code-graph/{repo_id}/call-chain", response_model=CodeGraphCallChainResponse)
def code_graph_call_chain(repo_id: str, symbol: str | None = Query(default=None),
                          function: str | None = Query(default=None, alias="function"),
                          direction: Literal["callers", "callees", "both"] = "both",
                          depth: int = Query(default=3, ge=1, le=10), snapshot_id: str | None = None) -> dict:
    _require_repo(repo_id)
    target = (symbol or function or "").strip()
    if not target:
        raise HTTPException(status_code=422, detail="symbol 或 function 不能为空。")
    selected = _resolve_snapshot(repo_id, snapshot_id)
    chain = get_call_chain(repo_id, target, direction, depth, selected)
    return {
        "repo_id": repo_id,
        "snapshot_id": selected,
        "symbol": target,
        "direction": direction,
        "depth": depth,
        **chain,
        # 旧接口以 chain 表示调用关系；新接口仍提供结构化 edges。
        "chain": chain["edges"],
        "stats": _graph_stats(repo_id, selected),
    }


@router.get("/api/v1/code-graph/{repo_id}/class", response_model=CodeGraphClassResponse)
def code_graph_class(repo_id: str, class_name: str = Query(min_length=1), snapshot_id: str | None = None) -> dict:
    _require_repo(repo_id)
    selected = _resolve_snapshot(repo_id, snapshot_id)
    relations = get_class_relations(repo_id, class_name, selected)
    return {
        "repo_id": repo_id,
        "snapshot_id": selected,
        "class_name": class_name,
        **relations,
        "stats": _graph_stats(repo_id, selected),
    }


@router.get("/api/v1/repos/{repo_id}/code-graph/stats", response_model=CodeGraphStatsResponse, include_in_schema=False)
def legacy_code_graph_stats(repo_id: str, snapshot_id: str | None = None) -> dict:
    return code_graph_stats(repo_id, snapshot_id)
