from __future__ import annotations

import pytest

from service.evaluation import (
    evaluate_citations,
    evaluate_rankings,
    evaluate_task_completion,
    evaluate_tool_parameter_validation,
    evaluate_tool_selection,
    summarize_durations,
)


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


def test_evaluate_task_completion_classifies_completed_missing_and_refused() -> None:
    result = evaluate_task_completion(
        confidences=["high", "low", "insufficient_evidence"],
        cited_paths=[["src/service.py"], ["src/missing.py"], []],
        known_paths=["src/service.py", "src/main.py"],
    )

    assert result == {
        "task_completion_query_count": 3,
        "task_completion_rate": 1 / 3,
        "task_completion_reasons": {
            "completed": 1,
            "citation_path_missing": 1,
            "relevant_evidence_missing": 0,
            "refused": 1,
        },
    }


def test_evaluate_task_completion_treats_empty_citations_as_missing() -> None:
    result = evaluate_task_completion(
        confidences=["high"],
        cited_paths=[[]],
        known_paths=["src/service.py"],
    )

    assert result["task_completion_reasons"] == {
        "completed": 0,
        "citation_path_missing": 1,
        "relevant_evidence_missing": 0,
        "refused": 0,
    }


def test_evaluate_task_completion_uses_configurable_refusal_confidence() -> None:
    result = evaluate_task_completion(
        confidences=["blocked"],
        cited_paths=[["src/service.py"]],
        known_paths=["src/service.py"],
        refusal_confidence="blocked",
    )

    assert result["task_completion_reasons"] == {
        "completed": 0,
        "citation_path_missing": 0,
        "relevant_evidence_missing": 0,
        "refused": 1,
    }


def test_evaluate_task_completion_requires_gold_evidence_when_provided() -> None:
    result = evaluate_task_completion(
        confidences=["high", "high"],
        cited_paths=[["src/service.py"], ["README.md"]],
        known_paths=["src/service.py", "README.md"],
        relevant_paths=[["src/service.py"], ["src/router.py"]],
    )

    assert result == {
        "task_completion_query_count": 2,
        "task_completion_rate": 0.5,
        "task_completion_reasons": {
            "completed": 1,
            "citation_path_missing": 0,
            "relevant_evidence_missing": 1,
            "refused": 0,
        },
    }


def test_evaluate_task_completion_rejects_empty_or_mismatched_inputs() -> None:
    with pytest.raises(ValueError, match="at least one"):
        evaluate_task_completion([], [], known_paths=[])
    with pytest.raises(ValueError, match="same number"):
        evaluate_task_completion(["high"], [], known_paths=[])
    with pytest.raises(ValueError, match="relevant_paths"):
        evaluate_task_completion(
            ["high"], [["src/service.py"]], known_paths=["src/service.py"], relevant_paths=[]
        )


def test_evaluate_tool_selection_reports_exact_match_missing_and_extra() -> None:
    result = evaluate_tool_selection(
        route_tools=[[], ["security_review"], ["dependency_impact"], ["language_structure"]],
        expected_tools=[[], ["security_review"], [], ["dependency_impact"]],
    )

    assert result == {
        "tool_selection_query_count": 4,
        "tool_selection_exact_match_rate": 0.5,
        "tool_selection_missing_rate": 0.25,
        "tool_selection_extra_rate": 0.5,
    }


def test_evaluate_tool_selection_counts_simultaneous_missing_and_extra_on_one_query() -> None:
    result = evaluate_tool_selection(
        route_tools=[["language_structure"]],
        expected_tools=[["security_review"]],
    )

    assert result["tool_selection_exact_match_rate"] == 0.0
    assert result["tool_selection_missing_rate"] == 1.0
    assert result["tool_selection_extra_rate"] == 1.0


def test_evaluate_tool_selection_rejects_empty_or_mismatched_inputs() -> None:
    with pytest.raises(ValueError, match="at least one"):
        evaluate_tool_selection([], [])
    with pytest.raises(ValueError, match="same number"):
        evaluate_tool_selection([[]], [])


def test_evaluate_tool_parameter_validation_reports_pass_rate() -> None:
    result = evaluate_tool_parameter_validation(
        ["succeeded", "parameter_error", "succeeded", "failed"]
    )

    assert result == {
        "tool_parameter_validation_count": 4,
        "tool_parameter_validation_pass_rate": 0.75,
        "tool_parameter_error_count": 1,
    }


def test_evaluate_tool_parameter_validation_uses_configurable_error_status() -> None:
    result = evaluate_tool_parameter_validation(["bad_args", "ok"], parameter_error_status="bad_args")

    assert result == {
        "tool_parameter_validation_count": 2,
        "tool_parameter_validation_pass_rate": 0.5,
        "tool_parameter_error_count": 1,
    }


def test_evaluate_tool_parameter_validation_rejects_empty_input() -> None:
    with pytest.raises(ValueError, match="at least one"):
        evaluate_tool_parameter_validation([])
