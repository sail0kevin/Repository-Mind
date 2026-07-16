"""默认关闭的 Embedding 实现，明确表示系统仅使用词法检索。"""
from __future__ import annotations

from service.core.embeddings.base import EmbeddingBatch, EmbeddingProvider


class DisabledEmbeddingProvider(EmbeddingProvider):
    """不调用网络，也不制造空向量占位。"""

    name = "disabled"
    model = ""
    enabled = False

    def embed(self, texts: list[str]) -> EmbeddingBatch:
        return EmbeddingBatch(vectors=[], provider=self.name, model=self.model)
