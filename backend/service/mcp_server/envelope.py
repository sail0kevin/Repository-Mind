"""
这个文件负责 MCP 工具的统一返回结构、长度封顶和参数裁剪。
所有 MCP 工具必须通过这里的 envelope()/error_envelope() 输出，禁止自行拼接返回结构。
"""
from __future__ import annotations

from typing import Any

MAX_SNIPPET_CHARS = 800
MAX_QUERY_CHARS = 400
MAX_LIMIT = 50
MAX_EVIDENCE_ITEMS = 30


def build_snippet(content: str, max_length: int = MAX_SNIPPET_CHARS) -> str:
    """把证据正文压缩成有长度上限的片段，避免单次调用产生无界上下文。"""
    normalized = " ".join((content or "").split())
    if len(normalized) <= max_length:
        return normalized
    return f"{normalized[:max_length].rstrip()}..."


def clamp_limit(limit: int | None, *, default: int, maximum: int = MAX_LIMIT) -> int:
    """把外部传入的 limit 裁剪到安全范围，避免非法或过大的值。"""
    if limit is None:
        return default
    try:
        value = int(limit)
    except (TypeError, ValueError):
        return default
    return max(1, min(value, maximum))


def clamp_text(value: str | None, max_length: int = MAX_QUERY_CHARS) -> str:
    """裁剪查询文本长度并去除首尾空白；None 或非字符串输入统一视为空字符串。"""
    if not isinstance(value, str):
        return ""
    return value.strip()[:max_length]


def evidence_item(row: dict[str, Any], *, reason: str | None = None) -> dict[str, Any]:
    """把内部证据行统一转换成 MCP 返回结构里的证据条目。"""
    return {
        "evidence_id": str(row.get("chunk_id") or row.get("id") or row.get("evidence_id") or ""),
        "file_path": str(row.get("file_path") or row.get("path") or ""),
        "start_line": row.get("start_line"),
        "end_line": row.get("end_line"),
        "snippet": build_snippet(str(row.get("content") or row.get("snippet") or "")),
        "reason": str(reason if reason is not None else (row.get("reason") or "")),
    }


def envelope(
    *,
    repo_id: str,
    snapshot_id: str | None = None,
    commit: str | None = None,
    status: str = "ok",
    data: dict[str, Any] | None = None,
    evidence: list[dict[str, Any]] | None = None,
    limitations: list[str] | None = None,
) -> dict[str, Any]:
    """构造统一的 MCP 工具返回结构；status 取值 ok/degraded/not_found/error。"""
    return {
        "repo_id": repo_id,
        "snapshot_id": snapshot_id,
        "commit": commit,
        "status": status,
        "data": data or {},
        "evidence": (evidence or [])[:MAX_EVIDENCE_ITEMS],
        "limitations": limitations or [],
    }


def error_envelope(
    repo_id: str,
    message: str,
    *,
    status: str = "error",
    snapshot_id: str | None = None,
    commit: str | None = None,
) -> dict[str, Any]:
    """异常统一转换成结构化 error，不让 MCP 进程崩溃，也不省略 repo_id。"""
    return envelope(
        repo_id=repo_id, snapshot_id=snapshot_id, commit=commit, status=status,
        data={}, evidence=[], limitations=[message],
    )
