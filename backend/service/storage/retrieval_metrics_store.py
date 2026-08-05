"""MCP 检索在线指标的持久化与聚合。"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from service.config.settings import get_settings
from service.storage.sqlite_db import get_connection

logger = logging.getLogger(__name__)
_LOW_SCORE_THRESHOLD = 0.01
_LOW_SCORE_STREAK = 10
_REDACTED_QUERY = "[redacted]"


def record_retrieval_metric(
    *,
    repo_id: str,
    snapshot_id: str,
    tool_name: str,
    retrieval_mode: str,
    query: str,
    returned_count: int,
    top_score: float | None,
    duration_ms: float,
) -> None:
    """保存一条不含原始查询文本的指标，并在连续低分时发出一次 warning。"""
    if get_settings().sqlite_read_only:
        return
    # 保留参数兼容 MCP 调用方，但在线聚合不需要也不应持久化用户查询。
    _ = query
    score = None if top_score is None else float(top_score)
    with get_connection() as connection:
        connection.execute(
            """INSERT INTO retrieval_metrics
               (id, repo_id, snapshot_id, tool_name, retrieval_mode, query,
                returned_count, top_score, duration_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                f"retrieval_metric_{uuid.uuid4().hex}",
                repo_id,
                snapshot_id,
                tool_name,
                retrieval_mode,
                _REDACTED_QUERY,
                max(0, int(returned_count)),
                score,
                max(0.0, float(duration_ms)),
            ),
        )
        rows = connection.execute(
            """SELECT top_score FROM retrieval_metrics
               WHERE repo_id = ? ORDER BY created_at DESC, rowid DESC LIMIT ?""",
            (repo_id, _LOW_SCORE_STREAK + 1),
        ).fetchall()
    if len(rows) >= _LOW_SCORE_STREAK and all(
        row[0] is None or float(row[0]) < _LOW_SCORE_THRESHOLD
        for row in rows[:_LOW_SCORE_STREAK]
    ):
        previous = rows[_LOW_SCORE_STREAK][0] if len(rows) > _LOW_SCORE_STREAK else None
        if len(rows) == _LOW_SCORE_STREAK or (
            previous is not None and float(previous) >= _LOW_SCORE_THRESHOLD
        ):
            logger.warning(
                "retrieval quality alert: %s consecutive low-score queries for repo %s",
                _LOW_SCORE_STREAK,
                repo_id,
            )


def _nearest_rank(values: list[float], percentile: float) -> float | None:
    """Return a deterministic nearest-rank percentile for local telemetry."""
    if not values:
        return None
    rank = max(1, int(len(values) * percentile + 0.999999999))
    return sorted(values)[rank - 1]


def _duration_summary(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {
            "average_duration_ms": None,
            "p50_duration_ms": None,
            "p95_duration_ms": None,
        }
    return {
        "average_duration_ms": sum(values) / len(values),
        "p50_duration_ms": _nearest_rank(values, 0.50),
        "p95_duration_ms": _nearest_rank(values, 0.95),
    }


def get_retrieval_metrics(*, days: int = 7, repo_id: str | None = None) -> dict:
    """返回最近几天按 UTC 日期聚合的检索质量趋势。"""
    days = min(30, max(1, int(days)))
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    where = "created_at >= ?"
    params: list[object] = [since]
    if repo_id:
        where += " AND repo_id = ?"
        params.append(repo_id)
    with get_connection() as connection:
        rows = connection.execute(
            f"""SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS request_count,
                       AVG(top_score) AS average_top_score,
                       MAX(top_score) AS maximum_top_score,
                       SUM(CASE WHEN top_score IS NULL OR top_score < ? THEN 1 ELSE 0 END) AS low_score_count
                FROM retrieval_metrics WHERE {where}
                GROUP BY day ORDER BY day""",
            [_LOW_SCORE_THRESHOLD, *params],
        ).fetchall()
        totals = connection.execute(
            f"""SELECT COUNT(*) AS request_count, AVG(top_score) AS average_top_score,
                       MAX(top_score) AS maximum_top_score
                FROM retrieval_metrics WHERE {where}""",
            params,
        ).fetchone()
        duration_rows = connection.execute(
            f"""SELECT substr(created_at, 1, 10) AS day, tool_name, retrieval_mode,
                       top_score, duration_ms
                FROM retrieval_metrics WHERE {where}
                ORDER BY created_at, rowid""",
            params,
        ).fetchall()

    duration_values = [float(row[4]) for row in duration_rows]
    durations_by_day: dict[str, list[float]] = {}
    breakdowns: dict[tuple[str, str], dict[str, object]] = {}
    for day, tool_name, retrieval_mode, top_score, duration_ms in duration_rows:
        durations_by_day.setdefault(day, []).append(float(duration_ms))
        key = (str(tool_name), str(retrieval_mode))
        breakdown = breakdowns.setdefault(
            key,
            {"request_count": 0, "low_score_count": 0, "durations": []},
        )
        breakdown["request_count"] = int(breakdown["request_count"]) + 1
        if top_score is None or float(top_score) < _LOW_SCORE_THRESHOLD:
            breakdown["low_score_count"] = int(breakdown["low_score_count"]) + 1
        breakdown["durations"].append(float(duration_ms))

    return {
        "days": days,
        "repo_id": repo_id,
        "totals": {
            "request_count": int(totals[0] or 0),
            "average_top_score": totals[1],
            "maximum_top_score": totals[2],
            **_duration_summary(duration_values),
        },
        "trend": [
            {
                "date": row[0],
                "request_count": int(row[1]),
                "average_top_score": row[2],
                "maximum_top_score": row[3],
                "low_score_count": int(row[4] or 0),
                **_duration_summary(durations_by_day.get(str(row[0]), [])),
            }
            for row in rows
        ],
        "breakdown": [
            {
                "tool_name": tool_name,
                "retrieval_mode": retrieval_mode,
                "request_count": int(values["request_count"]),
                "low_score_count": int(values["low_score_count"]),
                **_duration_summary(values["durations"]),
            }
            for (tool_name, retrieval_mode), values in sorted(breakdowns.items())
        ],
    }
