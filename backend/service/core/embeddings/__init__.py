"""RepoMind 的 provider-neutral Embedding 子系统。"""

from service.core.embeddings.base import EmbeddingBatch, EmbeddingError, EmbeddingProvider
from service.core.embeddings.disabled import DisabledEmbeddingProvider
from service.core.embeddings.openai_compatible import OpenAICompatibleEmbeddingProvider
from service.core.embeddings.service import EmbeddingRunStatus, embed_snapshot_evidence, resolve_embedding_provider

__all__ = [
    "DisabledEmbeddingProvider", "EmbeddingBatch", "EmbeddingError", "EmbeddingProvider",
    "EmbeddingRunStatus", "OpenAICompatibleEmbeddingProvider", "embed_snapshot_evidence",
    "resolve_embedding_provider",
]
