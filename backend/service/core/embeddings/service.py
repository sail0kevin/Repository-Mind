"""Embedding 配置解析、缓存复用与持久化编排。"""
from __future__ import annotations

from dataclasses import dataclass

from service.core.embeddings.base import EmbeddingError, EmbeddingProvider
from service.core.embeddings.disabled import DisabledEmbeddingProvider
from service.core.embeddings.openai_compatible import OpenAICompatibleEmbeddingProvider
from service.core.vector_store import find_cached_vector, store_evidence_vectors, update_chunk_embedding_statuses
from service.storage.secret_store import get_embedding_api_key
from service.storage.settings_store import get_setting


@dataclass(frozen=True)
class EmbeddingRunStatus:
    """快照向量阶段的可观察结果。"""

    status: str
    provider: str
    model: str
    stored: int = 0
    reused: int = 0
    warning: str | None = None


def resolve_embedding_provider() -> EmbeddingProvider:
    """只读取 Embedding 专属配置；默认 disabled，绝不复用 Chat 密钥。"""

    provider = str(get_setting("embedding_provider", "disabled") or "disabled").strip().lower()
    if provider in {"", "disabled", "none"}:
        return DisabledEmbeddingProvider()
    if provider != "openai_compatible":
        raise ValueError(f"不支持的 Embedding provider: {provider}")
    api_key = get_embedding_api_key() or ""
    if not api_key:
        raise ValueError("已启用 Embedding，但未配置 embedding_api_key")
    return OpenAICompatibleEmbeddingProvider(
        api_key=api_key,
        base_url=str(get_setting("embedding_base_url", "https://api.openai.com/v1")),
        model=str(get_setting("embedding_model", "text-embedding-3-small")),
    )


def embed_query(text: str) -> list[float] | None:
    """使用当前 Embedding 专属配置生成查询向量；不可用时返回 None 触发 lexical-only。"""

    try:
        provider = resolve_embedding_provider()
        if not provider.enabled:
            return None
        result = provider.embed([text])
        return result.vectors[0] if result.vectors else None
    except (EmbeddingError, ValueError, TypeError):
        return None


def embed_snapshot_evidence(repo_id: str, snapshot_id: str, evidence: list[dict], *, provider: EmbeddingProvider | None = None,
                            batch_size: int = 64) -> EmbeddingRunStatus:
    """复用同 provider/model/content_hash 的向量，仅为缺失内容调用供应商。"""

    try:
        selected = provider or resolve_embedding_provider()
    except Exception as exc:
        update_chunk_embedding_statuses(repo_id, snapshot_id, "warning")
        return EmbeddingRunStatus("warning", "configuration", "", warning=str(exc))
    if not selected.enabled:
        update_chunk_embedding_statuses(repo_id, snapshot_id, "disabled")
        return EmbeddingRunStatus("disabled", selected.name, selected.model, warning="Embedding 未配置，当前为 lexical-only。")

    records: list[dict] = []
    missing: list[dict] = []
    for item in evidence:
        cached = find_cached_vector(selected.name, selected.model, item["content_hash"])
        if cached is None:
            missing.append(item)
        else:
            records.append({**item, "vector": cached, "provider": selected.name, "model": selected.model})
    try:
        for start in range(0, len(missing), max(1, batch_size)):
            batch_items = missing[start:start + max(1, batch_size)]
            result = selected.embed([str(item.get("content") or "") for item in batch_items])
            for item, vector in zip(batch_items, result.vectors):
                records.append({**item, "vector": vector, "provider": result.provider, "model": result.model})
        store_evidence_vectors(repo_id, snapshot_id, records)
        update_chunk_embedding_statuses(repo_id, snapshot_id, "ready")
        return EmbeddingRunStatus("ready", selected.name, selected.model, stored=len(missing), reused=len(records) - len(missing))
    except (EmbeddingError, ValueError, TypeError) as exc:
        update_chunk_embedding_statuses(repo_id, snapshot_id, "warning")
        return EmbeddingRunStatus("warning", selected.name, selected.model, warning=str(exc))
