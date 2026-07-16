"""
这个文件负责知识片段的持久化与检索。
它在整个框架里扮演"片段存储层"的角色：保存切片后的代码/文档片段，并提供全文检索能力。
"""
from __future__ import annotations

import hashlib
from typing import Iterable

from service.storage.lexical_store import replace_snapshot_fts_rows, search_fts_chunks
from service.storage.sqlite_db import get_connection


def _active_snapshot_id(connection, repo_id: str) -> str | None:
    """查询 active 快照，所有旧查询默认复用这个范围。"""
    row = connection.execute("SELECT active_snapshot_id FROM repos WHERE id = ?", (repo_id,)).fetchone()
    return row["active_snapshot_id"] if row else None


def count_chunks(repo_id: str, snapshot_id: str | None = None) -> int:
    """统计指定快照片段数；未指定时统计 active。"""
    with get_connection() as connection:
        selected = snapshot_id if snapshot_id is not None else _active_snapshot_id(connection, repo_id)
        row = connection.execute(
            "SELECT COUNT(*) AS total FROM chunks WHERE repo_id = ? AND snapshot_id IS ?",
            (repo_id, selected),
        ).fetchone()
    return row["total"] if row else 0


def list_indexable_file_records(repo_id: str, snapshot_id: str | None = None) -> list[dict]:
    """列出指定快照中可安全交给文本解析器的文件。"""
    with get_connection() as connection:
        selected = snapshot_id if snapshot_id is not None else _active_snapshot_id(connection, repo_id)
        rows = connection.execute(
            """
            SELECT * FROM files
            WHERE repo_id = ? AND snapshot_id IS ?
              AND ignored_reason IS NULL
              AND is_binary = 0
              AND file_type = 'text'
            ORDER BY relative_path
            """,
            (repo_id, selected),
        ).fetchall()
    return [dict(row) for row in rows]


def _stable_chunk_id(repo_id: str, snapshot_id: str, item: dict) -> str:
    """片段 ID 由快照、文件、行范围和内容哈希稳定生成。"""
    identity = "\0".join(
        str(value or "")
        for value in (
            repo_id, snapshot_id, item.get("file_path"), item.get("start_line"),
            item.get("end_line"), item.get("content_hash"), item.get("chunk_type"),
        )
    )
    return f"chunk_{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:32]}"


def replace_repo_chunks(repo_id: str, chunks_by_file: dict[str, list[dict]], snapshot_id: str | None = None) -> int:
    """覆盖指定快照的知识片段，其他快照不受影响。"""
    with get_connection() as connection:
        selected = snapshot_id if snapshot_id is not None else _active_snapshot_id(connection, repo_id)
        connection.execute(
            "DELETE FROM chunks WHERE repo_id = ? AND snapshot_id IS ?", (repo_id, selected)
        )
        total = 0
        for items in chunks_by_file.values():
            for item in items:
                total += 1
                connection.execute(
                    """
                    INSERT INTO chunks (
                        id, repo_id, snapshot_id, file_id, file_path, chunk_type, title, symbol_name,
                        start_line, end_line, content, content_hash, token_count,
                        embedding_status, source_type, metadata_json, parent_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _stable_chunk_id(repo_id, selected or "legacy", item),
                        repo_id,
                        selected,
                        item.get("file_id"),
                        item.get("file_path"),
                        item.get("chunk_type", "text"),
                        item.get("title"),
                        item.get("symbol_name"),
                        item.get("start_line"),
                        item.get("end_line"),
                        item.get("content"),
                        item.get("content_hash"),
                        item.get("token_count"),
                        item.get("embedding_status", "pending"),
                        item.get("source_type", "text"),
                        item.get("metadata_json"),
                        item.get("parent_id"),
                    ),
                )
        # Chunk 兼容投影与 FTS 索引在同一事务内更新，任一失败都会整体回滚。
        replace_snapshot_fts_rows(connection, repo_id, selected)
    return total


def list_chunk_records(repo_id: str, limit: int = 100, snapshot_id: str | None = None) -> list[dict]:
    """列出指定快照片段；未指定时读取 active。"""
    with get_connection() as connection:
        selected = snapshot_id if snapshot_id is not None else _active_snapshot_id(connection, repo_id)
        rows = connection.execute(
            "SELECT * FROM chunks WHERE repo_id = ? AND snapshot_id IS ? ORDER BY file_path, start_line LIMIT ?",
            (repo_id, selected, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def get_chunk_record(repo_id: str, chunk_id: str, snapshot_id: str | None = None) -> dict | None:
    """读取指定或 active 快照中的单条知识片段。"""
    with get_connection() as connection:
        selected = snapshot_id if snapshot_id is not None else _active_snapshot_id(connection, repo_id)
        row = connection.execute(
            "SELECT * FROM chunks WHERE repo_id = ? AND snapshot_id IS ? AND id = ?",
            (repo_id, selected, chunk_id),
        ).fetchone()
    return dict(row) if row else None


def list_chunk_texts(repo_id: str, snapshot_id: str | None = None) -> list[str]:
    """列出指定快照的片段文本；默认读取 active。"""
    with get_connection() as connection:
        selected = snapshot_id if snapshot_id is not None else _active_snapshot_id(connection, repo_id)
        rows = connection.execute(
            "SELECT content FROM chunks WHERE repo_id = ? AND snapshot_id IS ?",
            (repo_id, selected),
        ).fetchall()
    return [row["content"] for row in rows if row["content"]]


def search_chunks(repo_id: str, query: str, limit: int = 10, snapshot_id: str | None = None) -> list[dict]:
    """保持旧 search/ask 契约，内部使用快照隔离的 FTS5 BM25。"""
    return search_fts_chunks(repo_id, query, limit=limit, snapshot_id=snapshot_id)
