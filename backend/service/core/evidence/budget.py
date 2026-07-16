"""Evidence Bundle 的预算配置与轻量 token 估算。"""
from __future__ import annotations

from dataclasses import dataclass
import re

_TOKEN_PATTERN = re.compile(r"[一-鿿]|[A-Za-z_][A-Za-z0-9_]*|\d+(?:\.\d+)?|[^\s]")


def estimate_tokens(text: str) -> int:
    """离线估算代码和中英文 token；用于硬预算，不冒充模型计费数字。"""
    if not text:
        return 0
    return max(1, len(_TOKEN_PATTERN.findall(text)))


@dataclass(frozen=True)
class EvidenceBudget:
    """证据装配的所有硬限制。"""

    total_tokens: int = 2400
    max_file_ratio: float = 0.5
    max_evidence_tokens: int = 600
    min_sources: int = 2
    max_items: int = 12

    def __post_init__(self) -> None:
        if self.total_tokens < 1 or self.max_evidence_tokens < 1 or self.max_items < 1:
            raise ValueError("token 和条目预算必须大于 0")
        if not 0 < self.max_file_ratio <= 1:
            raise ValueError("max_file_ratio 必须位于 (0, 1]")
        if self.min_sources < 1:
            raise ValueError("min_sources 必须大于 0")

    @property
    def max_file_tokens(self) -> int:
        return max(1, int(self.total_tokens * self.max_file_ratio))
