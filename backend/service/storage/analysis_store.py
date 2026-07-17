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


def save_analysis_report(report: dict, analysis_type: str = "workflow", snapshot_id: str | None = None) -> dict:
    """保存工作流分析报告，并固定到生成时使用的快照。"""

    repo_id = report["repo"]["repo_id"]
    with get_connection() as connection:
        selected = snapshot_id
        if selected is None:
            row = connection.execute("SELECT active_snapshot_id FROM repos WHERE id = ?", (repo_id,)).fetchone()
            selected = row["active_snapshot_id"] if row else None
        connection.execute(
            """
            INSERT OR REPLACE INTO analysis_reports (
                id, repo_id, snapshot_id, analysis_type, status, summary, report_json, markdown, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report["analysis_id"],
                repo_id,
                selected,
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
    """读取单份完整分析报告，并为旧 report_json 补齐快照元数据。"""

    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT report_json, snapshot_id,
                   (SELECT commit_hash FROM repository_snapshots WHERE id = analysis_reports.snapshot_id) AS commit_hash
            FROM analysis_reports WHERE id = ?
            """,
            (analysis_id,),
        ).fetchone()
    if row is None:
        return None
    report = json.loads(row["report_json"])
    # schema 7 之前的持久化 JSON 没有这两个字段；读取时从报告行绑定的快照回填，
    # 避免削弱新报告必须完整绑定快照的响应契约。
    report.setdefault("snapshot_id", row["snapshot_id"])
    report.setdefault("commit", row["commit_hash"])
    report.setdefault("response_type", "workflow_report")
    return report


def list_analysis_report_summaries(repo_id: str, limit: int = 12) -> list[dict]:
    """列出某个仓库最近的分析报告摘要。"""

    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, repo_id, snapshot_id, analysis_type, status, summary, created_at
            FROM analysis_reports
            WHERE repo_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (repo_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]
