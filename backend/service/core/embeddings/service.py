"""Embedding 配置解析、缓存复用与持久化编排。"""
from __future__ import annotations

import hashlib
import logging
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

from service.core.embeddings.base import EmbeddingError, EmbeddingProvider
from service.core.embeddings.disabled import DisabledEmbeddingProvider
from service.core.embeddings.openai_compatible import OpenAICompatibleEmbeddingProvider
from service.core.vector_store import find_cached_vector, store_evidence_vectors, update_chunk_embedding_statuses
from service.storage.secret_store import get_embedding_api_key
from service.storage.settings_store import get_setting

logger = logging.getLogger(__name__)
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
_LOOPBACK_PROBE_TIMEOUT_SECONDS = 0.2
_EMBEDDING_FALLBACK_MIN_CHARACTERS = 32


@dataclass(frozen=True)
class EmbeddingRunStatus:
    """快照向量阶段的可观察结果。"""

    status: str
    provider: str
    model: str
    stored: int = 0
    reused: int = 0
    warning: str | None = None


@dataclass(frozen=True)
class EmbeddingQueryConfiguration:
    """查询向量是否可在不触发网络请求的条件下创建。"""

    available: bool
    reason: str | None = None


def embedding_query_configuration() -> EmbeddingQueryConfiguration:
    """检查本地 Embedding 配置，不创建客户端也不请求 provider。"""

    provider = str(get_setting("embedding_provider", "disabled") or "disabled").strip().lower()
    if provider in {"", "disabled", "none"}:
        return EmbeddingQueryConfiguration(False, "embedding_provider_unconfigured")
    if provider != "openai_compatible":
        return EmbeddingQueryConfiguration(False, "embedding_provider_unsupported")
    try:
        api_key = get_embedding_api_key() or ""
    except Exception:  # Secret store failures must not block lexical retrieval.
        return EmbeddingQueryConfiguration(False, "embedding_provider_credentials_unavailable")
    if not api_key.strip():
        return EmbeddingQueryConfiguration(False, "embedding_provider_credentials_unavailable")
    base_url = str(get_setting("embedding_base_url", "https://api.openai.com/v1") or "").strip()
    if not base_url:
        return EmbeddingQueryConfiguration(False, "embedding_provider_invalid_configuration")
    if not str(get_setting("embedding_model", "text-embedding-3-small") or "").strip():
        return EmbeddingQueryConfiguration(False, "embedding_provider_invalid_configuration")
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return EmbeddingQueryConfiguration(False, "embedding_provider_invalid_configuration")
    host = (parsed.hostname or "").casefold()
    if host in _LOOPBACK_HOSTS:
        try:
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
        except ValueError:
            return EmbeddingQueryConfiguration(False, "embedding_provider_invalid_configuration")
        try:
            with socket.create_connection((host, port), timeout=_LOOPBACK_PROBE_TIMEOUT_SECONDS):
                pass
        except OSError:
            return EmbeddingQueryConfiguration(False, "embedding_provider_endpoint_unreachable")
    return EmbeddingQueryConfiguration(True)


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
    except (EmbeddingError, ValueError, TypeError) as exc:
        logger.warning("生成查询向量失败，回退到 lexical-only：%s", exc)
        return None


def embed_snapshot_evidence(repo_id: str, snapshot_id: str, evidence: list[dict], *, provider: EmbeddingProvider | None = None,
                            batch_size: int = 64, max_input_characters: int | None = None) -> EmbeddingRunStatus:
    """复用同 provider/model/content_hash 的向量，仅为缺失内容调用供应商。"""

    try:
        selected = provider or resolve_embedding_provider()
    except Exception as exc:
        update_chunk_embedding_statuses(repo_id, snapshot_id, "warning")
        return EmbeddingRunStatus("warning", "configuration", "", warning=str(exc))
    if not selected.enabled:
        update_chunk_embedding_statuses(repo_id, snapshot_id, "disabled")
        return EmbeddingRunStatus("disabled", selected.name, selected.model, warning="Embedding 未配置，当前为 lexical-only。")
    if max_input_characters is not None and max_input_characters <= 0:
        raise ValueError("max_input_characters must be positive when configured")

    records: list[dict] = []
    missing: list[dict] = []
    for item in evidence:
        content = str(item.get("content") or "")
        embedded_content = content[:max_input_characters] if max_input_characters is not None else content
        # Cache identity must represent exactly what was sent to the provider.
        embedded_hash = (
            hashlib.sha256(embedded_content.encode("utf-8")).hexdigest()
            if max_input_characters is not None
            else str(item["content_hash"])
        )
        embedding_item = {**item, "content": embedded_content, "content_hash": embedded_hash}
        cached = find_cached_vector(selected.name, selected.model, embedded_hash)
        if cached is None:
            missing.append(embedding_item)
        else:
            records.append({**embedding_item, "vector": cached, "provider": selected.name, "model": selected.model})
    failures: list[str] = []
    initial_reused = len(records)
    fallback_reused = 0

    def embed_batch(items: list[dict]) -> None:
        """Keep good provider calls when one input makes a batch fail."""
        nonlocal fallback_reused
        if not items:
            return
        try:
            result = selected.embed([str(item.get("content") or "") for item in items])
        except (EmbeddingError, ValueError, TypeError) as exc:
            if len(items) > 1:
                midpoint = max(1, len(items) // 2)
                embed_batch(items[:midpoint])
                embed_batch(items[midpoint:])
                return
            item = items[0]
            content = str(item.get("content") or "")
            fallback_length = min(len(content), max(_EMBEDDING_FALLBACK_MIN_CHARACTERS, len(content) // 2))
            while fallback_length >= _EMBEDDING_FALLBACK_MIN_CHARACTERS:
                fallback_content = content[:fallback_length]
                fallback_hash = hashlib.sha256(fallback_content.encode("utf-8")).hexdigest()
                cached = find_cached_vector(selected.name, selected.model, fallback_hash)
                if cached is not None:
                    fallback_reused += 1
                    records.append({**item, "content": fallback_content, "content_hash": fallback_hash,
                                    "vector": cached, "provider": selected.name, "model": selected.model})
                    return
                try:
                    fallback_result = selected.embed([fallback_content])
                    records.append({**item, "content": fallback_content, "content_hash": fallback_hash,
                                    "vector": fallback_result.vectors[0], "provider": fallback_result.provider,
                                    "model": fallback_result.model})
                    return
                except (EmbeddingError, ValueError, TypeError):
                    fallback_length //= 2
            failures.append(f"{item.get('id', '<unknown>')}: {exc}")
            return
        for item, vector in zip(items, result.vectors):
            records.append({**item, "vector": vector, "provider": result.provider, "model": result.model})

    for start in range(0, len(missing), max(1, batch_size)):
        embed_batch(missing[start:start + max(1, batch_size)])

    store_evidence_vectors(repo_id, snapshot_id, records)
    if failures:
        update_chunk_embedding_statuses(repo_id, snapshot_id, "warning")
        return EmbeddingRunStatus(
            "warning", selected.name, selected.model,
            stored=len(records) - initial_reused - fallback_reused,
            reused=initial_reused + fallback_reused,
            warning="; ".join(failures),
        )
    update_chunk_embedding_statuses(repo_id, snapshot_id, "ready")
    return EmbeddingRunStatus("ready", selected.name, selected.model, stored=len(missing), reused=len(records) - len(missing))
