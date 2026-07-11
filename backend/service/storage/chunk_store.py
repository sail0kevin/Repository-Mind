"""
这个文件负责知识片段的持久化与检索。
它在整个框架里扮演"片段存储层"的角色：保存切片后的代码/文档片段，并提供全文检索能力。
"""
from __future__ import annotations

import uuid
from collections import Counter
from typing import Iterable

from service.storage.sqlite_db import get_connection


def count_chunks(repo_id: str) -> int:
    """统计某个仓库已保存的知识片段总数。"""
    with get_connection() as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS total FROM chunks WHERE repo_id = ?",
            (repo_id,),
        ).fetchone()
    return row["total"] if row else 0


def list_indexable_file_records(repo_id: str) -> list[dict]:
    """列出可索引文件。"""
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM files WHERE repo_id = ? AND ignored_reason IS NULL",
            (repo_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def replace_repo_chunks(repo_id: str, chunks_by_file: dict[str, list[dict]]) -> int:
    """覆盖写入某个仓库的全部知识片段。"""
    with get_connection() as connection:
        connection.execute("DELETE FROM chunks WHERE repo_id = ?", (repo_id,))
        total = 0
        for items in chunks_by_file.values():
            for item in items:
                total += 1
                connection.execute(
                    """
                    INSERT INTO chunks (
                        id, repo_id, file_id, file_path, chunk_type, title, symbol_name,
                        start_line, end_line, content, content_hash, token_count,
                        embedding_status, source_type, metadata_json, parent_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"chunk_{uuid.uuid4().hex}",
                        repo_id,
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
    return total


def list_chunk_records(repo_id: str, limit: int = 100) -> list[dict]:
    """列出某个仓库最近的知识片段。"""
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM chunks WHERE repo_id = ? ORDER BY file_path, start_line LIMIT ?",
            (repo_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def get_chunk_record(repo_id: str, chunk_id: str) -> dict | None:
    """读取单条知识片段。"""
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM chunks WHERE repo_id = ? AND id = ?",
            (repo_id, chunk_id),
        ).fetchone()
    return dict(row) if row else None


def list_chunk_texts(repo_id: str) -> list[str]:
    """列出某个仓库所有知识片段的文本内容。"""
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT content FROM chunks WHERE repo_id = ?",
            (repo_id,),
        ).fetchall()
    return [row["content"] for row in rows if row["content"]]


def search_chunks(repo_id: str, query: str, limit: int = 10) -> list[dict]:
    """基于关键词倒排统计进行轻量文本检索。"""
    terms = [item.strip() for item in query.split() if item.strip()]
    if not terms:
        return []
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM chunks WHERE repo_id = ?",
            (repo_id,),
        ).fetchall()
    scored = []
    for row in rows:
        haystack = (row["content"] or "").lower()
        if not haystack:
            continue
        score = sum(haystack.count(term.lower()) for term in terms)
        if score <= 0:
            continue
        scored.append((score, row))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    results = []
    for score, row in scored[:limit]:
        data = dict(row)
        data["vector_score"] = 0.0
        data["score"] = float(score)
        results.append(data)
    return results
