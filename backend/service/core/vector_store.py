"""
这个文件负责本地向量索引的轻量封装。
它在整个框架里扮演"向量召回层"的角色：保存 embedding，并提供一个可被替换的相似度检索接口。


"""
from __future__ import annotations

import math
from collections import Counter

from service.storage.sqlite_db import get_connection


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    """计算两个向量的余弦相似度。"""
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def replace_repo_vector_index(repo_id: str, vectors: list[dict]) -> int:
    """覆盖写入某个仓库的向量索引。"""
    with get_connection() as connection:
        connection.execute("DELETE FROM vectors WHERE repo_id = ?", (repo_id,))
        for item in vectors:
            connection.execute(
                """
                INSERT INTO vectors (id, repo_id, chunk_id, embedding, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    item.get("id") or f"vec_{id(item)}",
                    repo_id,
                    item.get("chunk_id"),
                    item.get("embedding"),
                ),
            )
    return len(vectors)


def search_vectors(repo_id: str, query: str, limit: int = 8) -> list[dict]:
    """关键词加权的向量检索兜底实现。"""
    terms = [item for item in query.lower().split() if item]
    if not terms:
        return []
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT id, content FROM chunks WHERE repo_id = ?",
            (repo_id,),
        ).fetchall()
    scored = []
    for row in rows:
        haystack = (row["content"] or "").lower()
        score = sum(haystack.count(term) for term in terms)
        if score <= 0:
            continue
        scored.append({"chunk_id": row["id"], "vector_score": float(score)})
    scored.sort(key=lambda item: item["vector_score"], reverse=True)
    return scored[:limit]
