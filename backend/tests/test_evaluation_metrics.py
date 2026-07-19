from __future__ import annotations

import pytest

from service.evaluation import evaluate_citations, evaluate_rankings, summarize_durations


def test_evaluate_rankings_returns_reproducible_metrics() -> None:
    result = evaluate_rankings(
        [["noise.py", "target.py"], ["target.py", "other.py"]],
        [{"target.py"}, {"target.py"}],
    )

    assert result.to_dict() == {
        "query_count": 2,
        "recall_at_5": 1.0,
        "recall_at_10": 1.0,
        "mrr": 0.75,
    }


def test_evaluate_rankings_measures_fraction_of_all_relevant_items() -> None:
    result = evaluate_rankings(
        [["one.py", "noise.py"], ["two.py", "three.py"]],
        [{"one.py", "missing.py"}, {"two.py", "three.py"}],
    )

    assert result.recall_at_5 == 0.75
    assert result.recall_at_10 == 0.75

def test_evaluate_rankings_rejects_empty_or_mismatched_inputs() -> None:
    with pytest.raises(ValueError, match="at least one"):
        evaluate_rankings([], [])
    with pytest.raises(ValueError, match="same number"):
        evaluate_rankings([["target.py"]], [])


def test_summarize_durations_uses_deterministic_nearest_rank_percentiles() -> None:
    assert summarize_durations([4, 1, 9, 2]) == {
        "duration_count": 4,
        "duration_min_ms": 1.0,
        "duration_max_ms": 9.0,
        "duration_p50_ms": 2.0,
        "duration_p95_ms": 9.0,
    }


def test_summarize_durations_rejects_empty_or_negative_values() -> None:
    with pytest.raises(ValueError, match="at least one"):
        summarize_durations([])
    with pytest.raises(ValueError, match="non-negative"):
        summarize_durations([1, -1])


def test_evaluate_citations_reports_hit_rate_and_precision() -> None:
    result = evaluate_citations(
        [["src/service.py", "README.md"], ["noise.py"], []],
        [["src/service.py"], ["src/auth.py"], ["src/main.py"]],
    )

    assert result == {
        "citation_query_count": 3,
        "citation_hit_rate": 1 / 3,
        "citation_precision": 1 / 6,
    }
