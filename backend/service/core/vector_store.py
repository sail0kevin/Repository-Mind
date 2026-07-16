"""按快照隔离的 Evidence 向量存储与本地余弦检索。"""
from __future__ import annotations

from array import array
import hashlib
import math
import sys

from service.storage.sqlite_db import get_connection


def _pack_float32(values: list[float]) -> bytes:
    """将向量固定编码为 little-endian IEEE-754 float32 BLOB。"""

    packed = array("f", (float(value) for value in values))
    if sys.byteorder != "little":
        packed.byteswap()
    return packed.tobytes()


def _unpack_float32(value: bytes, dimension: int) -> list[float]:
    packed = array("f")
    packed.frombytes(value)
    if sys.byteorder != "little":
        packed.byteswap()
    if len(packed) != dimension:
        raise ValueError("向量 BLOB 长度与 dimension 不一致")
    return packed.tolist()


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    return 0.0 if left_norm == 0 or right_norm == 0 else dot / (left_norm * right_norm)


def find_cached_vector(provider: str, model: str, content_hash: str) -> list[float] | None:
    """跨快照复用内容相同且 provider/model 相同的真实向量。"""

    with get_connection() as connection:
        row = connection.execute(
            """SELECT vector, dimension FROM evidence_embeddings
               WHERE provider = ? AND model = ? AND content_hash = ?
               ORDER BY created_at DESC LIMIT 1""",
            (provider, model, content_hash),
        ).fetchone()
    return _unpack_float32(row["vector"], row["dimension"]) if row else None


def store_evidence_vectors(repo_id: str, snapshot_id: str, records: list[dict]) -> int:
    """原子写入向量，并绑定 snapshot/evidence/provider/model/dim/content_hash。"""

    if not records:
        return 0
    with get_connection() as connection:
        for record in records:
            vector = [float(value) for value in record["vector"]]
            if not vector:
                raise ValueError("不能保存空向量")
            identity = "\0".join((snapshot_id, record["id"], record["provider"], record["model"]))
            vector_id = f"emb_{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:32]}"
            connection.execute(
                """INSERT INTO evidence_embeddings
                       (id, repo_id, snapshot_id, evidence_id, provider, model, dimension, content_hash, vector)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(snapshot_id, evidence_id, provider, model) DO UPDATE SET
                       dimension = excluded.dimension, content_hash = excluded.content_hash,
                       vector = excluded.vector, created_at = CURRENT_TIMESTAMP""",
                (vector_id, repo_id, snapshot_id, record["id"], record["provider"], record["model"],
                 len(vector), record["content_hash"], _pack_float32(vector)),
            )
    return len(records)


def update_chunk_embedding_statuses(repo_id: str, snapshot_id: str, status: str) -> None:
    """让兼容 chunks API 明确展示 disabled/ready/warning。"""

    with get_connection() as connection:
        connection.execute(
            "UPDATE chunks SET embedding_status = ? WHERE repo_id = ? AND snapshot_id = ?",
            (status, repo_id, snapshot_id),
        )


def has_real_embeddings(repo_id: str, snapshot_id: str | None = None) -> bool:
    with get_connection() as connection:
        selected = snapshot_id
        if selected is None:
            row = connection.execute("SELECT active_snapshot_id FROM repos WHERE id = ?", (repo_id,)).fetchone()
            selected = row["active_snapshot_id"] if row else None
        row = connection.execute(
            "SELECT 1 FROM evidence_embeddings WHERE repo_id = ? AND snapshot_id IS ? LIMIT 1",
            (repo_id, selected),
        ).fetchone()
    return row is not None


def search_vectors(repo_id: str, query: str, limit: int = 8, *, query_embedding: list[float] | None = None,
                   snapshot_id: str | None = None) -> list[dict]:
    """对指定快照的真实 float32 Evidence 向量执行余弦检索。"""

    if not query.strip() or not query_embedding:
        return []
    with get_connection() as connection:
        selected = snapshot_id
        if selected is None:
            row = connection.execute("SELECT active_snapshot_id FROM repos WHERE id = ?", (repo_id,)).fetchone()
            selected = row["active_snapshot_id"] if row else None
        rows = connection.execute(
            """SELECT chunks.*, embeddings.vector, embeddings.dimension
               FROM evidence_embeddings embeddings JOIN chunks
                 ON chunks.id = embeddings.evidence_id AND chunks.snapshot_id = embeddings.snapshot_id
               WHERE embeddings.repo_id = ? AND embeddings.snapshot_id IS ?""",
            (repo_id, selected),
        ).fetchall()
    scored = []
    for row in rows:
        vector = _unpack_float32(row["vector"], row["dimension"])
        score = _cosine_similarity(query_embedding, vector)
        if score > 0:
            item = dict(row)
            item.update(score=score, vector_score=score, match_type="semantic")
            item.pop("vector", None)
            scored.append(item)
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:limit]


# 兼容旧调用名；M3 不再写入旧 vectors JSON 表。
def replace_repo_vector_index(repo_id: str, vectors: list[dict], snapshot_id: str | None = None) -> int:
    return 0
