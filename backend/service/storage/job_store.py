"""
这个文件负责索引任务和后台任务的持久化。
它在整个框架里扮演“任务状态机”角色，保证状态转换、时间和进度都一致。
"""
from __future__ import annotations

import uuid

from service.storage.sqlite_db import get_connection

JOB_STATUSES = {"queued", "running", "succeeded", "failed", "cancelled", "interrupted"}
TERMINAL_JOB_STATUSES = {"succeeded", "failed", "cancelled", "interrupted"}


def create_job_record(
    job_type: str,
    repo_id: str | None = None,
    message: str | None = None,
    snapshot_id: str | None = None,
) -> str:
    """创建 queued 任务，真正执行时再进入 running，并可绑定目标快照。"""
    job_id = f"job_{uuid.uuid4().hex}"
    with get_connection() as connection:
        connection.execute(
            """INSERT INTO jobs (id, repo_id, snapshot_id, job_type, status, progress, message)
               VALUES (?, ?, ?, ?, 'queued', 0.0, ?)""",
            (job_id, repo_id, snapshot_id, job_type, message or ""),
        )
    return job_id


def start_job_record(job_id: str, message: str | None = None) -> bool:
    """把 queued 任务原子地切换为 running，并首次写入 started_at。"""
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE jobs
            SET status = 'running', started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
                message = COALESCE(?, message), updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = 'queued'
            """,
            (message, job_id),
        )
    return cursor.rowcount == 1


def update_job_progress(job_id: str, progress: float, message: str | None = None) -> None:
    """仅更新 running 任务，并用 MAX 保证进度单调且限制在 0 到 1。"""
    normalized = max(0.0, min(float(progress), 1.0))
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE jobs
            SET progress = MAX(progress, ?), message = COALESCE(?, message), updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = 'running'
            """,
            (normalized, message, job_id),
        )


def update_job_snapshot(job_id: str, snapshot_id: str) -> None:
    """把 ingest 任务绑定到实际构建的快照。"""
    with get_connection() as connection:
        connection.execute(
            "UPDATE jobs SET snapshot_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (snapshot_id, job_id),
        )


def update_job_repo(job_id: str, repo_id: str) -> None:
    """在任务创建后补录 repo_id。"""
    with get_connection() as connection:
        connection.execute(
            "UPDATE jobs SET repo_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (repo_id, job_id),
        )


def finish_job_record(
    job_id: str,
    status: str,
    message: str | None = None,
    error: str | None = None,
    progress: float | None = None,
) -> bool:
    """把 queued/running 任务结束为终态，拒绝非法状态和二次结束。"""
    if status not in TERMINAL_JOB_STATUSES:
        raise ValueError(f"非法任务终态: {status}")
    normalized = None if progress is None else max(0.0, min(float(progress), 1.0))
    if status == "succeeded":
        normalized = 1.0 if normalized is None else normalized
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE jobs
            SET status = ?, message = COALESCE(?, message), error = ?,
                progress = CASE WHEN ? IS NULL THEN progress ELSE MAX(progress, ?) END,
                finished_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status IN ('queued', 'running')
            """,
            (status, message, error, normalized, normalized, job_id),
        )
    return cursor.rowcount == 1


def recover_interrupted_jobs(message: str = "应用上次退出时任务仍在运行，已标记为中断") -> int:
    """应用启动时恢复不可能继续执行的陈旧 running 任务。"""
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE jobs
            SET status = 'interrupted', message = ?, finished_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE status IN ('queued', 'running')
            """,
            (message,),
        )
    return cursor.rowcount


def get_job_record(job_id: str) -> dict | None:
    """读取一条任务记录。"""
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row else None
