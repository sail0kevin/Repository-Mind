"""可选语义检索适配器：只有查询向量可用时才参与融合。"""
from __future__ import annotations

from collections.abc import Callable

from service.core.embeddings.service import embed_query
from service.core.vector_store import has_real_embeddings, search_vectors


class SemanticRetriever:
    """封装查询向量提供器与现有向量索引，缺能力时明确降级。"""

    name = "semantic"

    def __init__(
        self,
        query_embedder: Callable[[str], list[float] | None] | None = embed_query,
        search: Callable[..., list[dict]] = search_vectors,
        availability: Callable[..., bool] = has_real_embeddings,
    ) -> None:
        self.query_embedder = query_embedder
        self.search = search
        self.availability = availability

    def available(self, repo_id: str, snapshot_id: str) -> bool:
        return self.query_embedder is not None and self.availability(repo_id, snapshot_id)

    def retrieve(self, repo_id: str, snapshot_id: str, query: str, limit: int) -> list[dict]:
        if self.query_embedder is None:
            return []
        query_embedding = self.query_embedder(query)
        if not query_embedding:
            return []
        rows = self.search(
            repo_id,
            query,
            limit=limit,
            query_embedding=query_embedding,
            snapshot_id=snapshot_id,
        )
        results: list[dict] = []
        for rank, row in enumerate(rows, start=1):
            item = dict(row)
            item["chunk_id"] = item.get("chunk_id") or item.get("id")
            item["retriever"] = self.name
            item["rank"] = rank
            item["signals"] = sorted(set(item.get("signals", [])) | {"semantic"})
            item["reason"] = item.get("reason") or "语义匹配"
            results.append(item)
        return results
