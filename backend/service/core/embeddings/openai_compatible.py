"""OpenAI-compatible Embedding 适配器。"""
from __future__ import annotations

import math
from typing import Any, Callable

from service.core.embeddings.base import EmbeddingBatch, EmbeddingError, EmbeddingProvider


class OpenAICompatibleEmbeddingProvider(EmbeddingProvider):
    """通过 OpenAI SDK 契约调用兼容服务，客户端工厂可在测试中替换。"""

    name = "openai_compatible"
    enabled = True

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float = 60.0,
        client_factory: Callable[..., Any] | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Embedding API Key 不能为空")
        if not base_url.strip():
            raise ValueError("Embedding Base URL 不能为空")
        if not model.strip():
            raise ValueError("Embedding 模型不能为空")
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.model = model.strip()
        self.timeout = timeout
        self._client_factory = client_factory

    def _client(self) -> Any:
        if self._client_factory is not None:
            return self._client_factory(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout)
        try:
            from openai import OpenAI
        except Exception as exc:
            raise EmbeddingError("openai SDK 未安装") from exc
        return OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout)

    def embed(self, texts: list[str]) -> EmbeddingBatch:
        if not texts:
            return EmbeddingBatch(vectors=[], provider=self.name, model=self.model)
        try:
            response = self._client().embeddings.create(model=self.model, input=texts, encoding_format="float")
            data = list(response.data)
            ordered = sorted(data, key=lambda item: int(getattr(item, "index", 0)))
            vectors = [[float(value) for value in item.embedding] for item in ordered]
        except EmbeddingError:
            raise
        except Exception as exc:
            raise EmbeddingError("Embedding 接口调用失败") from exc
        if len(vectors) != len(texts):
            raise EmbeddingError("Embedding 响应数量与输入不一致")
        dimension = len(vectors[0]) if vectors else 0
        if dimension <= 0 or any(len(vector) != dimension for vector in vectors):
            raise EmbeddingError("Embedding 响应维度无效或不一致")
        if any(not math.isfinite(value) for vector in vectors for value in vector):
            raise EmbeddingError("Embedding 响应包含非有限数值")
        return EmbeddingBatch(vectors=vectors, provider=self.name, model=self.model)
