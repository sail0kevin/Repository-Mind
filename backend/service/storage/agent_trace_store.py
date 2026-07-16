"""Main Agent 执行轨迹存储；只保存脱敏摘要和 Evidence 引用。"""
from __future__ import annotations

import json
import uuid
from typing import Any

from service.storage.sqlite_db import get_connection


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def start_agent_trace(repo_id: str, snapshot_id: str, question: str, *, entrypoint: str = "ask",
                      mode: str = "auto", planner_version: str = "rule-router-v1") -> str:
    """创建 running trace，并固定仓库与快照。"""
    trace_id = f"trace_{uuid.uuid4().hex}"
    with get_connection() as connection:
        connection.execute(
            """INSERT INTO agent_traces
                   (id, repo_id, snapshot_id, entrypoint, question, mode, status, planner_version)
               VALUES (?, ?, ?, ?, ?, ?, 'running', ?)""",
            (trace_id, repo_id, snapshot_id, entrypoint, question, mode, planner_version),
        )
    return trace_id


def record_agent_step(trace_id: str, step_no: int, step_type: str, *, tool_name: str | None = None,
                      status: str = "succeeded", input_summary: dict | None = None,
                      output_summary: dict | None = None, evidence_refs: list[dict] | None = None,
                      token_count: int = 0, duration_ms: float | None = None,
                      error: str | None = None) -> str:
    """按顺序保存一个路由、工具、综合或降级步骤。"""
    step_id = f"trace_step_{uuid.uuid4().hex}"
    with get_connection() as connection:
        connection.execute(
            """INSERT INTO agent_trace_steps
                   (id, trace_id, step_no, step_type, tool_name, status, input_json,
                    output_summary_json, evidence_refs_json, token_count, duration_ms, error, completed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (step_id, trace_id, step_no, step_type, tool_name, status,
             _json(input_summary or {}), _json(output_summary or {}), _json(evidence_refs or []),
             max(0, int(token_count)), duration_ms, error),
        )
    return step_id


def finish_agent_trace(trace_id: str, *, status: str, answer: str, confidence: str,
                       token_count: int = 0, error: str | None = None) -> None:
    """完成 trace；fallback 是成功返回但明确使用规则降级。"""
    with get_connection() as connection:
        connection.execute(
            """UPDATE agent_traces
               SET status = ?, final_answer = ?, confidence = ?, token_count = ?, error = ?,
                   completed_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (status, answer, confidence, max(0, int(token_count)), error, trace_id),
        )


def bind_trace_session(trace_id: str, session_id: str) -> None:
    """回答保存为 session 后建立反向关联。"""
    with get_connection() as connection:
        connection.execute("UPDATE agent_traces SET session_id = ? WHERE id = ?", (session_id, trace_id))


def get_agent_trace(repo_id: str, trace_id: str) -> dict | None:
    """读取 trace 及有序步骤，拒绝跨仓库访问。"""
    with get_connection() as connection:
        trace = connection.execute(
            "SELECT * FROM agent_traces WHERE id = ? AND repo_id = ?", (trace_id, repo_id)
        ).fetchone()
        if trace is None:
            return None
        steps = connection.execute(
            "SELECT * FROM agent_trace_steps WHERE trace_id = ? ORDER BY step_no", (trace_id,)
        ).fetchall()
    result = dict(trace)
    result["steps"] = []
    for row in steps:
        item = dict(row)
        item["input"] = json.loads(item.pop("input_json") or "{}")
        item["output_summary"] = json.loads(item.pop("output_summary_json") or "{}")
        item["evidence_refs"] = json.loads(item.pop("evidence_refs_json") or "[]")
        result["steps"].append(item)
    return result
