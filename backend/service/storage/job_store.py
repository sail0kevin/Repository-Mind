"""
这个文件负责索引任务和后台任务的持久化。
它在整个框架里扮演"任务存储层"的角色：把 ingest、workflow_analysis 等异步任务的状态写进 SQLite。
"""
from __future__ import annotations

import uuid

from service.storage.sqlite_db import get_connection


def create_job_record(job_type: str, repo_id: str | None = None, message: str | None = None) -> str:
    """创建一条任务记录。"""
    job_id = f"job_{uuid.uuid4().hex}"
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO jobs (id, repo_id, job_type, status, progress, message)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (job_id, repo_id, job_type, "queued", 0.0, message or ""),
        )
    return job_id


def update_job_progress(job_id: str, progress: float, message: str | None = None) -> None:
    """更新任务进度和消息。"""
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE jobs
            SET progress = ?, message = COALESCE(?, message), updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (progress, message, job_id),
        )


def update_job_repo(job_id: str, repo_id: str) -> None:
    """在任务创建后补录 repo_id。"""
    with get_connection() as connection:
        connection.execute(
            "UPDATE jobs SET repo_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (repo_id, job_id),
        )


def finish_job_record(job_id: str, status: str, message: str | None = None, error: str | None = None, progress: float | None = None) -> None:
    """结束一条任务。"""
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE jobs
            SET status = ?,
                message = COALESCE(?, message),
                error = COALESCE(?, error),
                finished_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status, message, error, job_id),
        )
        if progress is not None:
            connection.execute(
                "UPDATE jobs SET progress = ? WHERE id = ?",
                (progress, job_id),
            )


def get_job_record(job_id: str) -> dict | None:
    """读取一条任务记录。"""
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
    return dict(row) if row else None
