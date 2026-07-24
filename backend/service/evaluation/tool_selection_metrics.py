"""工具选择（Router）准确率与参数校验通过率指标。"""
from __future__ import annotations

from typing import Iterable, Sequence


def evaluate_tool_selection(
    route_tools: Sequence[Iterable[str]],
    expected_tools: Sequence[Iterable[str]],
) -> dict[str, int | float]:
    """按查询对比 Router 实际调用工具集合与 gold 标注的期望工具集合。

    每条查询先判定是否完全匹配（含双方都不调用任何工具的情况）；不完全匹配时
    分别记录是否存在"该调用但未调用"（missing）和"不该调用但调用了"（extra）——
    这两者可能同时出现在同一条查询里，因此三个比率的分母都是查询总数，不要求
    互斥求和为 1。
    """

    if not route_tools:
        raise ValueError("tool selection evaluation requires at least one query")
    if len(route_tools) != len(expected_tools):
        raise ValueError("route_tools and expected_tools must contain the same number of queries")

    exact_match = 0
    missing = 0
    extra = 0
    for actual, expected in zip(route_tools, expected_tools):
        actual_set = {str(item) for item in actual}
        expected_set = {str(item) for item in expected}
        if actual_set == expected_set:
            exact_match += 1
            continue
        if expected_set - actual_set:
            missing += 1
        if actual_set - expected_set:
            extra += 1

    count = len(route_tools)
    return {
        "tool_selection_query_count": count,
        "tool_selection_exact_match_rate": exact_match / count,
        "tool_selection_missing_rate": missing / count,
        "tool_selection_extra_rate": extra / count,
    }


def evaluate_tool_parameter_validation(
    outcomes: Sequence[str],
    *,
    parameter_error_status: str = "parameter_error",
) -> dict[str, int | float]:
    """计算工具调用里因参数问题失败的比例，通过率 = 1 - 该比例。

    截至本模块实现时，`main_agent.py` 的工具调用只有笼统的 succeeded/failed
    两态，尚未把参数错误和其他异常分开归类（该分类由另一项独立任务负责产出）。
    当前没有任何采集流程会真实产出 `parameter_error_status` 取值，这里先把
    输入契约定下来，单测覆盖的是分类落地后才会真实出现的状态取值，避免分类
    数据源就位后还要改这个模块的公开接口。
    """

    if not outcomes:
        raise ValueError("tool parameter validation evaluation requires at least one outcome")

    parameter_errors = sum(1 for status in outcomes if status == parameter_error_status)
    count = len(outcomes)
    return {
        "tool_parameter_validation_count": count,
        "tool_parameter_validation_pass_rate": (count - parameter_errors) / count,
        "tool_parameter_error_count": parameter_errors,
    }
