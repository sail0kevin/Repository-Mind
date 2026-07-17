"""
这个文件负责仓库和文件记录的本地持久化。
它在整个框架里扮演"仓库存储层"的角色：把注册后的仓库元数据和扫描到的文件清单写入 SQLite。
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
import uuid
from typing import Iterable

from service.storage.sqlite_db import get_connection


def normalize_repo_path(repo_path) -> str:
    """规范化本地源路径；Windows 路径比较忽略大小写和分隔符差异。"""
    resolved = str(Path(repo_path).expanduser().resolve(strict=False))
    return os.path.normcase(os.path.normpath(resolved))


def normalize_remote_url(remote_url: str | None) -> str | None:
    """规范化 remote URL，兼容 GitHub 尾部斜杠和 .git 写法。"""
    if not remote_url or not remote_url.strip():
        return None
    value = remote_url.strip()
    parsed = urlsplit(value)
    if parsed.scheme and parsed.netloc:
        path = parsed.path.rstrip("/")
        if path.lower().endswith(".git"):
            path = path[:-4]
        return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path.lower(), "", ""))
    return value.rstrip("/").removesuffix(".git").lower()


def find_repo_by_source(repo_path=None, remote_url: str | None = None) -> dict | None:
    """按规范本地路径或 remote URL 查找已注册源，避免生成重复 repo_id。"""
    path_key = normalize_repo_path(repo_path) if repo_path is not None else None
    remote_key = normalize_remote_url(remote_url)
    for record in list_repo_records(limit=1000):
        if remote_key and normalize_remote_url(record.get("remote_url")) == remote_key:
            return record
        if path_key and normalize_repo_path(record["repo_path"]) == path_key:
            return record
    return None


def create_repo_record(
    repo_path,
    alias: str,
    remote_url: str | None = None,
    branch: str | None = None,
    current_commit: str | None = None,
) -> str:
    """创建仓库记录；同一本地路径或 remote URL 重复注册时复用 repo_id。"""
    existing = find_repo_by_source(repo_path, remote_url)
    if existing is not None:
        return existing["id"]
    repo_id = f"repo_{uuid.uuid4().hex}"
    normalized_path = str(Path(repo_path).expanduser().resolve(strict=False))
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO repos (id, alias, repo_path, remote_url, branch, commit_hash, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (repo_id, alias, normalized_path, remote_url, branch, current_commit, "registered"),
        )
    return repo_id


def list_repo_records(limit: int = 100) -> list[dict]:
    """列出最近注册的仓库，供仓库选择器和 Snapshot API 使用。"""
    normalized_limit = max(1, min(int(limit), 1000))
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT repos.*, snapshots.commit_hash AS active_commit_hash,
                   snapshots.status AS active_snapshot_status
            FROM repos
            LEFT JOIN repository_snapshots snapshots ON snapshots.id = repos.active_snapshot_id
            ORDER BY repos.created_at DESC LIMIT ?
            """,
            (normalized_limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_repo_record(repo_id: str) -> dict | None:
    """读取仓库记录。"""
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM repos WHERE id = ?",
            (repo_id,),
        ).fetchone()
    return dict(row) if row else None


def _stable_file_id(repo_id: str, snapshot_id: str, relative_path: str) -> str:
    """文件 ID 只由快照和规范相对路径决定，重试不会产生重复记录。"""
    normalized = relative_path.replace("\\", "/")
    digest = hashlib.sha256(f"{repo_id}\0{snapshot_id}\0{normalized}".encode("utf-8")).hexdigest()[:32]
    return f"file_{digest}"


def list_file_records(
    repo_id: str,
    limit: int = 1000,
    snapshot_id: str | None = None,
    offset: int = 0,
) -> list[dict]:
    """分页列出指定快照文件；未指定时兼容地读取 active 快照。"""
    if limit < 1 or offset < 0:
        raise ValueError("文件记录分页参数无效。")
    with get_connection() as connection:
        selected_snapshot = snapshot_id
        if selected_snapshot is None:
            row = connection.execute("SELECT active_snapshot_id FROM repos WHERE id = ?", (repo_id,)).fetchone()
            selected_snapshot = row["active_snapshot_id"] if row else None
        rows = connection.execute(
            "SELECT * FROM files WHERE repo_id = ? AND snapshot_id IS ? ORDER BY relative_path LIMIT ? OFFSET ?",
            (repo_id, selected_snapshot, limit, offset),
        ).fetchall()
    return [dict(row) for row in rows]


def get_file_record(repo_id: str, file_id: str, snapshot_id: str | None = None) -> dict | None:
    """读取文件记录；默认只允许访问 active 快照。"""
    with get_connection() as connection:
        selected_snapshot = snapshot_id
        if selected_snapshot is None:
            repo = connection.execute("SELECT active_snapshot_id FROM repos WHERE id = ?", (repo_id,)).fetchone()
            selected_snapshot = repo["active_snapshot_id"] if repo else None
        row = connection.execute(
            "SELECT * FROM files WHERE repo_id = ? AND snapshot_id IS ? AND id = ?",
            (repo_id, selected_snapshot, file_id),
        ).fetchone()
    return dict(row) if row else None


def replace_file_records(repo_id: str, files: Iterable[dict], snapshot_id: str | None = None) -> int:
    """覆盖指定快照的文件；新 ingest 必须显式传 snapshot_id。"""
    file_list = list(files)
    with get_connection() as connection:
        selected_snapshot = snapshot_id
        if selected_snapshot is None:
            repo = connection.execute("SELECT active_snapshot_id FROM repos WHERE id = ?", (repo_id,)).fetchone()
            selected_snapshot = repo["active_snapshot_id"] if repo else None
        connection.execute(
            "DELETE FROM files WHERE repo_id = ? AND snapshot_id IS ?", (repo_id, selected_snapshot)
        )
        for item in file_list:
            relative_path = item.get("relative_path") or ""
            file_id = _stable_file_id(repo_id, selected_snapshot or "legacy", relative_path)
            connection.execute(
                """
                INSERT INTO files (
                    id, repo_id, snapshot_id, relative_path, absolute_path, language, file_type,
                    extension, size_bytes, line_count, is_binary, is_test_file,
                    ignored_reason, hash, parse_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    file_id,
                    repo_id,
                    selected_snapshot,
                    relative_path,
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
