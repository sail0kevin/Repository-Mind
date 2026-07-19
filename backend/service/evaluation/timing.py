"""可复现的延迟摘要计算。"""
from __future__ import annotations

import math
from typing import Iterable


def summarize_durations(duration_ms: Iterable[float]) -> dict[str, float | int]:
    """返回 count/min/max/P50/P95；使用 nearest-rank，避免小样本插值歧义。"""

    values = sorted(float(value) for value in duration_ms)
    if not values:
        raise ValueError("duration summary requires at least one value")
    if any(value < 0 for value in values):
        raise ValueError("duration must be non-negative")

    def percentile(rate: float) -> float:
        index = max(0, math.ceil(rate * len(values)) - 1)
        return values[index]

    return {
        "duration_count": len(values),
        "duration_min_ms": values[0],
        "duration_max_ms": values[-1],
        "duration_p50_ms": percentile(0.50),
        "duration_p95_ms": percentile(0.95),
    }
