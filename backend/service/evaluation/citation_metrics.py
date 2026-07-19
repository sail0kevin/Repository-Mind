"""证据引用质量指标。"""
from __future__ import annotations

from typing import Iterable, Sequence


def evaluate_citations(
    cited_paths: Sequence[Iterable[str]],
    relevant_paths: Sequence[Iterable[str]],
) -> dict[str, float | int]:
    """计算按查询聚合的证据命中率与引用精确率。

    命中率表示每条查询是否至少引用了一个人工标注的相关路径；精确率表示
    所有被引用路径中有多少属于标注集合。空引用会得到 0 命中率和 0 精确率。
    """

    if not cited_paths:
        raise ValueError("citation evaluation requires at least one query")
    if len(cited_paths) != len(relevant_paths):
        raise ValueError("cited and relevant must contain the same number of queries")

    hits = 0
    precision_values: list[float] = []
    for cited, relevant in zip(cited_paths, relevant_paths):
        cited_set = {str(path) for path in cited if path}
        relevant_set = {str(path) for path in relevant if path}
        overlap = cited_set & relevant_set
        hits += bool(overlap)
        precision_values.append(len(overlap) / len(cited_set) if cited_set else 0.0)

    count = len(cited_paths)
    return {
        "citation_query_count": count,
        "citation_hit_rate": hits / count,
        "citation_precision": sum(precision_values) / count,
    }
