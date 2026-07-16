"""定义与供应商无关的 Embedding 契约。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


class EmbeddingError(RuntimeError):
    """Embedding 供应商调用或响应校验失败。"""


@dataclass(frozen=True)
class EmbeddingBatch:
    """一次批量向量化的标准结果。"""

    vectors: list[list[float]]
    provider: str
    model: str


class EmbeddingProvider(ABC):
    """所有 Embedding 适配器必须实现的最小接口。"""

    name: str
    model: str
    enabled: bool = True

    @abstractmethod
    def embed(self, texts: list[str]) -> EmbeddingBatch:
        """按输入顺序返回向量。"""
