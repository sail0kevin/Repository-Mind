"""可选语义检索适配器：只有查询向量可用时才参与融合。"""
from __future__ import annotations

from collections.abc import Callable

from service.core.embeddings.service import embedding_query_configuration, embed_query
from service.core.vector_store import has_real_embeddings, search_vectors


class SemanticRetriever:
    """封装查询向量提供器与现有向量索引，缺能力时明确降级。"""

    name = "semantic"

    def __init__(
        self,
        query_embedder: Callable[[str], list[float] | None] | None = embed_query,
        search: Callable[..., list[dict]] = search_vectors,
        availability: Callable[..., bool] = has_real_embeddings,
        query_configuration: Callable[[], object] | None = None,
    ) -> None:
        self.query_embedder = query_embedder
        self.search = search
        self.availability = availability
        self.query_configuration = (
            embedding_query_configuration if query_configuration is None and query_embedder is embed_query
            else query_configuration
        )

    def unavailable_reason(self) -> str | None:
        """Return an immediately knowable configuration reason without calling a provider."""

        if self.query_embedder is None:
            return "query_embedder_unavailable"
        if self.query_configuration is None:
            return None
        status = self.query_configuration()
        if bool(getattr(status, "available", status)):
            return None
        return str(getattr(status, "reason", "embedding_provider_unconfigured"))

    def available(self, repo_id: str, snapshot_id: str) -> bool:
        return self.unavailable_reason() is None and self.availability(repo_id, snapshot_id)

    def retrieve(self, repo_id: str, snapshot_id: str, query: str, limit: int) -> list[dict]:
        results, _ = self.retrieve_with_status(repo_id, snapshot_id, query, limit)
        return results

    def retrieve_with_status(
        self, repo_id: str, snapshot_id: str, query: str, limit: int
    ) -> tuple[list[dict], bool]:
        """Return results and whether a query embedding was actually available."""
        if self.query_embedder is None:
            return [], False
        query_embedding = self.query_embedder(query)
        if not query_embedding:
            return [], False
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
            item["semantic_score"] = float(item.get("semantic_score", item.get("vector_score", item.get("score", 0.0))))
            item["retriever"] = self.name
            item["rank"] = rank
            item["signals"] = sorted(set(item.get("signals", [])) | {"semantic"})
            item["reason"] = item.get("reason") or "语义匹配"
            results.append(item)
        return results, True
