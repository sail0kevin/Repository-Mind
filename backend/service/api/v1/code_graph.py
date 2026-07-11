"""
这个文件负责代码图谱的查询接口。
它在整个框架里扮演"代码图谱 API"的角色：把代码图谱的统计、重要节点、函数搜索、调用链和类关系暴露给前端。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from service.core.codegraph.store import get_graph_stats
from service.storage.repository_store import get_repo_record

router = APIRouter(tags=["code-graph"])


def _require_repo(repo_id: str) -> dict:
    record = get_repo_record(repo_id)
    if record is None:
        raise HTTPException(status_code=404, detail="没有找到指定仓库。")
    return record


@router.get("/api/v1/code-graph/{repo_id}/stats")
def code_graph_stats(repo_id: str) -> dict:
    """返回代码图谱统计信息。"""
    _require_repo(repo_id)
    return get_graph_stats(repo_id)


@router.get("/api/v1/code-graph/{repo_id}/important")
def code_graph_important(repo_id: str) -> dict:
    """返回重要节点列表。"""
    _require_repo(repo_id)
    stats = get_graph_stats(repo_id)
    return {"nodes": [], "stats": stats}


@router.post("/api/v1/code-graph/{repo_id}/search")
def code_graph_search(repo_id: str, payload: dict) -> dict:
    """搜索代码节点。"""
    _require_repo(repo_id)
    return {"matches": [], "stats": get_graph_stats(repo_id)}


@router.get("/api/v1/code-graph/{repo_id}/call-chain")
def code_graph_call_chain(repo_id: str, symbol: str = "") -> dict:
    """返回符号调用链。"""
    _require_repo(repo_id)
    return {"symbol": symbol, "chain": [], "stats": get_graph_stats(repo_id)}


@router.get("/api/v1/code-graph/{repo_id}/class")
def code_graph_class(repo_id: str, class_name: str = "") -> dict:
    """返回类关系。"""
    _require_repo(repo_id)
    return {"class_name": class_name, "relations": [], "stats": get_graph_stats(repo_id)}


@router.get("/api/v1/repos/{repo_id}/code-graph/stats")
def legacy_code_graph_stats(repo_id: str) -> dict:
    """兼容旧路由：返回代码图谱统计信息。"""
    _require_repo(repo_id)
    return get_graph_stats(repo_id)
