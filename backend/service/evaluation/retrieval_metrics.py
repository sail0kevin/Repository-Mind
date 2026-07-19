"""检索质量指标。"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable, Sequence


@dataclass(frozen=True)
class RetrievalMetrics:
    """一组查询的检索质量结果。"""

    query_count: int
    recall_at_5: float
    recall_at_10: float
    mrr: float

    def to_dict(self) -> dict[str, float | int]:
        return asdict(self)


def evaluate_rankings(
    ranked: Sequence[Sequence[str]],
    relevant: Sequence[Iterable[str]],
) -> RetrievalMetrics:
    """计算 Recall@5、Recall@10 和 MRR。

    空评测集和长度不一致都会显式抛出异常，避免生成没有统计意义的数字。
    """

    if not ranked:
        raise ValueError("ranking evaluation requires at least one query")
    if len(ranked) != len(relevant):
        raise ValueError("ranked and relevant must contain the same number of queries")

    expected_sets = [set(items) for items in relevant]
    recall5 = sum(
        len(set(items[:5]) & expected) / len(expected) if expected else 0.0
        for items, expected in zip(ranked, expected_sets)
    )
    recall10 = sum(
        len(set(items[:10]) & expected) / len(expected) if expected else 0.0
        for items, expected in zip(ranked, expected_sets)
    )
    reciprocal_ranks = [
        next((1.0 / rank for rank, item in enumerate(items, start=1) if item in expected), 0.0)
        for items, expected in zip(ranked, expected_sets)
    ]

    count = len(ranked)
    return RetrievalMetrics(
        query_count=count,
        recall_at_5=recall5 / count,
        recall_at_10=recall10 / count,
        mrr=sum(reciprocal_ranks) / count,
    )
