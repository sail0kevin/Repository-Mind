"""
这个文件负责工作流分析报告的本地持久化。
它让首次仓库分析不只停留在一次响应里，而是可以被 UI 再次读取和复用。
"""

from datetime import UTC, datetime
import json

from service.storage.sqlite_db import get_connection


def utc_now() -> str:
    """返回 ISO 格式 UTC 时间。"""

    return datetime.now(UTC).isoformat()


def save_analysis_report(report: dict, analysis_type: str = "workflow") -> dict:
    """保存工作流分析报告，并返回报告本身。"""

    repo_id = report["repo"]["repo_id"]
    with get_connection() as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO analysis_reports (
                id, repo_id, analysis_type, status, summary, report_json, markdown, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report["analysis_id"],
                repo_id,
                analysis_type,
                report["status"],
                report["summary"],
                json.dumps(report, ensure_ascii=False),
                report["markdown"],
                utc_now(),
            ),
        )
    return report


def get_analysis_report(analysis_id: str) -> dict | None:
    """读取单份完整分析报告。"""

    with get_connection() as connection:
        row = connection.execute(
            "SELECT report_json FROM analysis_reports WHERE id = ?",
            (analysis_id,),
        ).fetchone()
    if row is None:
        return None
    return json.loads(row["report_json"])


def list_analysis_report_summaries(repo_id: str, limit: int = 12) -> list[dict]:
    """列出某个仓库最近的分析报告摘要。"""

    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, repo_id, analysis_type, status, summary, created_at
            FROM analysis_reports
            WHERE repo_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (repo_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]
