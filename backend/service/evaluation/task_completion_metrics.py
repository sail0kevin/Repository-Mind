"""任务完成率指标。"""
from __future__ import annotations

from typing import Iterable, Sequence


def evaluate_task_completion(
    confidences: Sequence[str],
    cited_paths: Sequence[Iterable[str]],
    known_paths: Iterable[str],
    *,
    relevant_paths: Sequence[Iterable[str]] | None = None,
    refusal_confidence: str = "insufficient_evidence",
) -> dict[str, int | float | dict[str, int]]:
    """计算 Router 分发→工具执行→证据组装→答案生成全链路的任务完成率。

    判定为完成的条件：confidence 不是拒答态、引用列表非空、引用路径均能在
    known_paths（目标仓库真实文件集合）中找到，并且至少命中一条人工标注的
    relevant_paths。这样可避免“随便引用一个真实文件”也被计作任务完成。

    relevant_paths 为 None 时保留旧的路径有效性判定，供尚未建立 Gold 标注的
    数据集使用；正式任务完成率应传入每条任务的人工标注关键证据。

    注意：`refusal_confidence` 对应的拒答态目前尚未在生产代码中真实产出（拒答
    机制属于独立任务），这里的分类分支是为该状态落地后即可直接生效而预留的。
    """

    if not confidences:
        raise ValueError("task completion evaluation requires at least one query")
    if len(confidences) != len(cited_paths):
        raise ValueError("confidences and cited_paths must contain the same number of queries")
    if relevant_paths is not None and len(confidences) != len(relevant_paths):
        raise ValueError("confidences and relevant_paths must contain the same number of queries")

    known = {str(path) for path in known_paths}
    reasons = {
        "completed": 0,
        "citation_path_missing": 0,
        "relevant_evidence_missing": 0,
        "refused": 0,
    }
    gold_rows = relevant_paths if relevant_paths is not None else [None] * len(confidences)
    for confidence, cited, relevant in zip(confidences, cited_paths, gold_rows):
        cited_list = [str(path) for path in cited if path]
        if confidence == refusal_confidence:
            reasons["refused"] += 1
        elif not cited_list or any(path not in known for path in cited_list):
            reasons["citation_path_missing"] += 1
        elif relevant is not None and not set(cited_list).intersection(str(path) for path in relevant):
            reasons["relevant_evidence_missing"] += 1
        else:
            reasons["completed"] += 1

    count = len(confidences)
    return {
        "task_completion_query_count": count,
        "task_completion_rate": reasons["completed"] / count,
        "task_completion_reasons": reasons,
    }
