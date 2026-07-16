"""
这个文件负责仓库快照的生命周期、归属校验和原子发布。
同一仓库同一 commit 只有一个稳定快照，只有 succeeded 快照可以成为 active。
"""
from __future__ import annotations

import hashlib

from service.storage.sqlite_db import get_connection

SNAPSHOT_STATUSES = {"building", "succeeded", "failed", "cancelled"}


def stable_snapshot_id(repo_id: str, commit_hash: str) -> str:
    """根据非空仓库 ID 和规范化 commit 生成跨进程稳定 ID。"""
    normalized_repo = repo_id.strip()
    normalized_commit = commit_hash.strip().lower()
    if not normalized_repo:
        raise ValueError("repo_id 不能为空")
    if not normalized_commit:
        raise ValueError("commit_hash 不能为空")
    digest = hashlib.sha256(f"{normalized_repo}\0{normalized_commit}".encode("utf-8")).hexdigest()
    return f"snap_{digest}"


def create_or_get_snapshot(repo_id: str, commit_hash: str, branch: str | None = None) -> dict:
    """API 兼容包装：返回同一 commit 的唯一快照记录。"""
    return get_or_create_snapshot(repo_id, commit_hash, branch)[0]


def get_or_create_snapshot(repo_id: str, commit_hash: str, branch: str | None = None) -> tuple[dict, bool]:
    """并发安全地读取或创建 building 快照。"""
    normalized_commit = commit_hash.strip().lower()
    snapshot_id = stable_snapshot_id(repo_id, normalized_commit)
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO repository_snapshots
                (id, repo_id, commit_hash, branch, status)
            VALUES (?, ?, ?, ?, 'building')
            """,
            (snapshot_id, repo_id.strip(), normalized_commit, branch),
        )
        row = connection.execute(
            "SELECT * FROM repository_snapshots WHERE repo_id = ? AND commit_hash = ?",
            (repo_id.strip(), normalized_commit),
        ).fetchone()
    if row is None:
        raise RuntimeError("快照创建后未能读取")
    return dict(row), cursor.rowcount == 1


def retry_failed_snapshot(repo_id: str, snapshot_id: str, branch: str | None = None) -> bool:
    """只允许本仓库 failed 快照回到 building，清理工作由 ingest 在锁内完成。"""
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE repository_snapshots
            SET status = 'building', branch = COALESCE(?, branch), error = NULL,
                started_at = CURRENT_TIMESTAMP, completed_at = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND repo_id = ? AND status = 'failed'
            """,
            (branch, snapshot_id, repo_id),
        )
    return cursor.rowcount == 1


def publish_snapshot(repo_id: str, snapshot_id: str, branch: str | None, file_count: int) -> bool:
    """在一个事务内完成 succeeded、active 和仓库元数据更新。"""
    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        snapshot = connection.execute(
            """
            SELECT commit_hash FROM repository_snapshots
            WHERE id = ? AND repo_id = ? AND status = 'building'
            """,
            (snapshot_id, repo_id),
        ).fetchone()
        if snapshot is None:
            connection.rollback()
            return False
        connection.execute(
            """
            UPDATE repository_snapshots
            SET status = 'succeeded', error = NULL, completed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (snapshot_id,),
        )
        connection.execute(
            """
            UPDATE repos
            SET active_snapshot_id = ?, branch = ?, commit_hash = ?, status = 'indexed', file_count = ?
            WHERE id = ?
            """,
            (snapshot_id, branch, snapshot["commit_hash"], file_count, repo_id),
        )
        connection.commit()
    return True


def finish_snapshot(snapshot_id: str, status: str, error: str | None = None) -> bool:
    """测试和旧调用兼容的合法终态转换。"""
    if status not in {"succeeded", "failed", "cancelled"}:
        raise ValueError(f"非法快照终态: {status}")
    with get_connection() as connection:
        cursor = connection.execute(
            """UPDATE repository_snapshots SET status = ?, error = ?, completed_at = CURRENT_TIMESTAMP,
                      updated_at = CURRENT_TIMESTAMP WHERE id = ? AND status = 'building'""",
            (status, error if status == "failed" else None, snapshot_id),
        )
    return cursor.rowcount == 1


def set_active_snapshot(repo_id: str, snapshot_id: str) -> bool:
    """仅允许把本仓库 succeeded 快照设为 active。"""
    with get_connection() as connection:
        snapshot = connection.execute(
            "SELECT commit_hash, branch FROM repository_snapshots WHERE id = ? AND repo_id = ? AND status = 'succeeded'",
            (snapshot_id, repo_id),
        ).fetchone()
        if snapshot is None:
            return False
        count = connection.execute("SELECT COUNT(*) FROM files WHERE repo_id = ? AND snapshot_id = ?", (repo_id, snapshot_id)).fetchone()[0]
        cursor = connection.execute(
            "UPDATE repos SET active_snapshot_id = ?, commit_hash = ?, branch = ?, file_count = ? WHERE id = ?",
            (snapshot_id, snapshot["commit_hash"], snapshot["branch"], count, repo_id),
        )
    return cursor.rowcount == 1


def fail_snapshot(snapshot_id: str, error: str) -> bool:
    """仅允许 building 进入 failed，绝不修改 active。"""
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE repository_snapshots
            SET status = 'failed', error = ?, completed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = 'building'
            """,
            (error, snapshot_id),
        )
    return cursor.rowcount == 1


def recover_building_snapshots(message: str = "应用上次退出时快照仍在构建，已标记失败") -> int:
    """启动恢复时把不可能继续执行的 building 快照标记 failed。"""
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE repository_snapshots
            SET status = 'failed', error = ?, completed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE status = 'building'
            """,
            (message,),
        )
    return cursor.rowcount


def get_snapshot(snapshot_id: str) -> dict | None:
    """按 ID 读取快照。"""
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM repository_snapshots WHERE id = ?", (snapshot_id,)).fetchone()
    return dict(row) if row else None


def get_repo_snapshot(repo_id: str, snapshot_id: str) -> dict | None:
    """读取属于指定仓库的快照，跨仓库时返回 None。"""
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM repository_snapshots WHERE id = ? AND repo_id = ?",
            (snapshot_id, repo_id),
        ).fetchone()
    return dict(row) if row else None


def list_snapshots(repo_id: str, limit: int = 100) -> list[dict]:
    """按创建时间倒序列出仓库快照。"""
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT * FROM repository_snapshots WHERE repo_id = ?
            ORDER BY created_at DESC, id DESC LIMIT ?
            """,
            (repo_id, max(1, min(int(limit), 1000))),
        ).fetchall()
    return [dict(row) for row in rows]


def get_active_snapshot(repo_id: str) -> dict | None:
    """只返回本仓库当前 succeeded active 快照。"""
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT snapshots.* FROM repository_snapshots snapshots
            JOIN repos ON repos.active_snapshot_id = snapshots.id
            WHERE repos.id = ? AND snapshots.repo_id = repos.id AND snapshots.status = 'succeeded'
            """,
            (repo_id,),
        ).fetchone()
    return dict(row) if row else None
