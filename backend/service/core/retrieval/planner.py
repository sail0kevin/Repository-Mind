"""检索规划器：把一次查询转换为可审计、确定性的检索计划。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

RetrievalMode = Literal["lexical", "hybrid"]


@dataclass(frozen=True)
class RetrievalPlan:
    """一次检索需要执行的通道和候选数量。"""

    query: str
    mode: RetrievalMode
    limit: int
    candidate_limit: int
    use_lexical: bool = True
    use_semantic: bool = False
    expand_structural: bool = True


class RetrievalPlanner:
    """根据可用能力生成计划；首版不包含任何 LLM reranker。"""

    def __init__(self, candidate_multiplier: int = 4, max_candidates: int = 200) -> None:
        self.candidate_multiplier = max(1, candidate_multiplier)
        self.max_candidates = max(1, max_candidates)

    def plan(self, query: str, limit: int, *, semantic_available: bool) -> RetrievalPlan:
        cleaned = " ".join(query.split())
        safe_limit = max(1, min(int(limit), 50))
        candidates = min(self.max_candidates, max(safe_limit, safe_limit * self.candidate_multiplier))
        return RetrievalPlan(
            query=cleaned,
            mode="hybrid" if semantic_available else "lexical",
            limit=safe_limit,
            candidate_limit=candidates,
            use_semantic=semantic_available,
        )
