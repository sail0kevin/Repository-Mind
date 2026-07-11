"""
这个文件负责仓库和文件记录的本地持久化。
它在整个框架里扮演"仓库存储层"的角色：把注册后的仓库元数据和扫描到的文件清单写入 SQLite。
"""
from __future__ import annotations

import uuid
from typing import Iterable

from service.storage.sqlite_db import get_connection


def create_repo_record(
    repo_path,
    alias: str,
    remote_url: str | None = None,
    branch: str | None = None,
    current_commit: str | None = None,
) -> str:
    """创建一条仓库记录，并返回生成的 repo_id。"""
    repo_id = f"repo_{uuid.uuid4().hex}"
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO repos (id, alias, repo_path, remote_url, branch, commit_hash, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (repo_id, alias, str(repo_path), remote_url, branch, current_commit, "registered"),
        )
    return repo_id


def get_repo_record(repo_id: str) -> dict | None:
    """读取仓库记录。"""
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM repos WHERE id = ?",
            (repo_id,),
        ).fetchone()
    return dict(row) if row else None


def list_file_records(repo_id: str, limit: int = 1000) -> list[dict]:
    """列出某个仓库的文件记录。"""
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM files WHERE repo_id = ? ORDER BY relative_path LIMIT ?",
            (repo_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def get_file_record(repo_id: str, file_id: str) -> dict | None:
    """读取单条文件记录。"""
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM files WHERE repo_id = ? AND id = ?",
            (repo_id, file_id),
        ).fetchone()
    return dict(row) if row else None


def replace_file_records(repo_id: str, files: Iterable[dict]) -> int:
    """覆盖写入某个仓库的全部文件记录。"""
    file_list = list(files)
    with get_connection() as connection:
        connection.execute("DELETE FROM files WHERE repo_id = ?", (repo_id,))
        for item in file_list:
            file_id = f"file_{uuid.uuid4().hex}"
            connection.execute(
                """
                INSERT INTO files (
                    id, repo_id, relative_path, absolute_path, language, file_type,
                    extension, size_bytes, line_count, is_binary, is_test_file,
                    ignored_reason, hash, parse_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    file_id,
                    repo_id,
                    item.get("relative_path"),
                    item.get("absolute_path"),
                    item.get("language"),
                    item.get("file_type"),
                    item.get("extension"),
                    item.get("size_bytes"),
                    item.get("line_count"),
                    1 if item.get("is_binary") else 0,
                    1 if item.get("is_test_file") else 0,
                    item.get("ignored_reason"),
                    item.get("hash"),
                    item.get("parse_status", "pending"),
                ),
            )
    return len(file_list)
