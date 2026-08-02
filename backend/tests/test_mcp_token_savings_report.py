from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "report_mcp_token_savings.py"
SPEC = importlib.util.spec_from_file_location("report_mcp_token_savings", SCRIPT)
assert SPEC and SPEC.loader
REPORTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPORTER)


def _hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _row(
    task_id: str,
    mode: str,
    *,
    input_tokens: int,
    output_tokens: int,
    source_characters_received: int,
    passed: bool,
) -> dict[str, object]:
    return {
        "task_id": task_id,
        "mode": mode,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "source_characters_received": source_characters_received,
        "passed": passed,
        "usage_provenance": "codex_exec_json.turn.completed" if passed else None,
        "raw_trace_sha256": _hash(f"{task_id}/{mode}") if passed else None,
    }


def _write_run(
    tmp_path: Path,
    *,
    benchmark_id: str = "run-a",
    model: str = "gpt-test",
    commit: str = "a" * 40,
) -> Path:
    metadata = {
        "benchmark_id": benchmark_id,
        "codex_version": "0.1.0",
        "model": model,
        "reasoning_effort": "low",
        "bypass_sandbox": True,
        "timeout_seconds": 120,
        "commit": commit,
        "mcp_profile": "coding-agent",
    }
    results = [
        _row("both-pass", "baseline", input_tokens=100, output_tokens=20, source_characters_received=500, passed=True),
        _row("both-pass", "treatment", input_tokens=60, output_tokens=10, source_characters_received=120, passed=True),
        _row("baseline-only", "baseline", input_tokens=1000, output_tokens=100, source_characters_received=2000, passed=True),
        _row("baseline-only", "treatment", input_tokens=1, output_tokens=1, source_characters_received=1, passed=False),
    ]
    (tmp_path / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    (tmp_path / "results.json").write_text(json.dumps(results), encoding="utf-8")
    batch = {
        "batch_id": "mcp-token-test",
        "runs": [{"benchmark_id": benchmark_id, "results": "results.json", "metadata": "metadata.json"}],
    }
    path = tmp_path / "batch.json"
    path.write_text(json.dumps(batch), encoding="utf-8")
    return path


def test_report_uses_only_both_passed_tasks_and_reports_total_tokens(tmp_path: Path) -> None:
    report = REPORTER.build_report(_write_run(tmp_path))

    aggregate = report["aggregate"]
    assert aggregate["task_count"] == 2
    assert aggregate["both_passed_count"] == 1
    assert aggregate["baseline_only_passed_count"] == 1
    assert aggregate["treatment_only_passed_count"] == 0
    assert aggregate["both_failed_count"] == 0
    assert aggregate["baseline_input_tokens"] == 100
    assert aggregate["treatment_input_tokens"] == 60
    assert aggregate["input_tokens_saved"] == 40
    assert aggregate["input_tokens_saving_percent"] == 40.0
    assert aggregate["baseline_total_tokens"] == 120
    assert aggregate["treatment_total_tokens"] == 70
    assert aggregate["total_tokens_saved"] == 50
    assert aggregate["total_tokens_saving_percent"] == pytest.approx(41.67)
    assert aggregate["baseline_pass_rate"] == 1.0
    assert aggregate["treatment_pass_rate"] == 0.5


def test_report_rejects_missing_usage_provenance_for_a_successful_task(tmp_path: Path) -> None:
    batch_path = _write_run(tmp_path)
    results_path = tmp_path / "results.json"
    results = json.loads(results_path.read_text(encoding="utf-8"))
    results[0]["usage_provenance"] = "manual-estimate"
    results_path.write_text(json.dumps(results), encoding="utf-8")

    with pytest.raises(REPORTER.TokenSavingsReportError, match="usage_provenance"):
        REPORTER.build_report(batch_path)


def test_report_rejects_incompatible_agent_conditions(tmp_path: Path) -> None:
    batch_path = _write_run(tmp_path)
    second = tmp_path / "second"
    second.mkdir()
    _write_run(second, benchmark_id="run-b", model="other-model")
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    batch["runs"].append(
        {
            "benchmark_id": "run-b",
            "results": "second/results.json",
            "metadata": "second/metadata.json",
        }
    )
    batch_path.write_text(json.dumps(batch), encoding="utf-8")

    with pytest.raises(REPORTER.TokenSavingsReportError, match="incompatible conditions: model"):
        REPORTER.build_report(batch_path)


def test_report_rejects_mixed_mcp_profiles(tmp_path: Path) -> None:
    batch_path = _write_run(tmp_path)
    second = tmp_path / "second"
    second.mkdir()
    _write_run(second, benchmark_id="run-b")
    metadata_path = second / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["mcp_profile"] = "full"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    batch["runs"].append(
        {
            "benchmark_id": "run-b",
            "results": "second/results.json",
            "metadata": "second/metadata.json",
        }
    )
    batch_path.write_text(json.dumps(batch), encoding="utf-8")

    with pytest.raises(REPORTER.TokenSavingsReportError, match="incompatible conditions: mcp_profile"):
        REPORTER.build_report(batch_path)


def test_report_rejects_mixed_timeout_budgets(tmp_path: Path) -> None:
    batch_path = _write_run(tmp_path)
    second = tmp_path / "second"
    second.mkdir()
    _write_run(second, benchmark_id="run-b")
    metadata_path = second / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["timeout_seconds"] = 240
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    batch["runs"].append(
        {
            "benchmark_id": "run-b",
            "results": "second/results.json",
            "metadata": "second/metadata.json",
        }
    )
    batch_path.write_text(json.dumps(batch), encoding="utf-8")

    with pytest.raises(REPORTER.TokenSavingsReportError, match="incompatible conditions: timeout_seconds"):
        REPORTER.build_report(batch_path)


def test_report_allows_distinct_fixed_repository_commits(tmp_path: Path) -> None:
    batch_path = _write_run(tmp_path, benchmark_id="click", commit="a" * 40)
    second = tmp_path / "second"
    second.mkdir()
    _write_run(second, benchmark_id="typer", commit="b" * 40)
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    batch["runs"].append(
        {
            "benchmark_id": "typer",
            "results": "second/results.json",
            "metadata": "second/metadata.json",
        }
    )
    batch_path.write_text(json.dumps(batch), encoding="utf-8")

    report = REPORTER.build_report(batch_path)

    assert report["aggregate"]["task_count"] == 4
    assert [run["commit"] for run in report["runs"]] == ["a" * 40, "b" * 40]


def test_markdown_marks_zero_baseline_saving_as_not_available(tmp_path: Path) -> None:
    batch_path = _write_run(tmp_path)
    results_path = tmp_path / "results.json"
    results = json.loads(results_path.read_text(encoding="utf-8"))
    results[0]["input_tokens"] = 0
    results[1]["input_tokens"] = 0
    results_path.write_text(json.dumps(results), encoding="utf-8")

    rendered = REPORTER.render_markdown(REPORTER.build_report(batch_path))
    assert "| Input tokens | 0 | 0 | 0 | n/a% |" in rendered


def test_report_requires_formal_acceptance_gates(tmp_path: Path) -> None:
    batch_path = _write_run(tmp_path)
    report = REPORTER.build_report(batch_path)

    assert report["schema_version"] == "mcp-token-savings-report-v2"
    assert report["acceptance"]["status"] == "not_accepted"
    assert "repository_count" in report["acceptance"]["failed_gates"]
    assert "independent_repeats" in report["acceptance"]["failed_gates"]
    assert "treatment_pass_rate" in report["acceptance"]["failed_gates"]
    assert report["acceptance"]["publishable_token_conclusion"] is False


def test_report_aggregates_failure_classes(tmp_path: Path) -> None:
    batch_path = _write_run(tmp_path)
    results_path = tmp_path / "results.json"
    results = json.loads(results_path.read_text(encoding="utf-8"))
    results[1]["passed"] = False
    results[1]["status"] = "timeout"
    results[1]["failure_class"] = "timeout_after_mcp_before_final_answer"
    results_path.write_text(json.dumps(results), encoding="utf-8")

    report = REPORTER.build_report(batch_path)

    assert report["failure_classes"] == {
        "rubric_failed": 1,
        "timeout_after_mcp_before_final_answer": 1,
    }
    assert report["failure_classes_by_cohort"] == {
        "baseline": {},
        "treatment": {
            "rubric_failed": 1,
            "timeout_after_mcp_before_final_answer": 1,
        },
    }
    assert report["statuses"]["timeout"] == 1
    assert report["statuses_by_cohort"]["treatment"]["timeout"] == 1


def test_report_exposes_paired_outcome_matrix(tmp_path: Path) -> None:
    batch_path = _write_run(tmp_path)
    results_path = tmp_path / "results.json"
    results = json.loads(results_path.read_text(encoding="utf-8"))
    results.extend(
        [
            _row("treatment-only", "baseline", input_tokens=1, output_tokens=1, source_characters_received=1, passed=False),
            _row("treatment-only", "treatment", input_tokens=10, output_tokens=2, source_characters_received=20, passed=True),
            _row("both-failed", "baseline", input_tokens=1, output_tokens=1, source_characters_received=1, passed=False),
            _row("both-failed", "treatment", input_tokens=1, output_tokens=1, source_characters_received=1, passed=False),
        ]
    )
    results_path.write_text(json.dumps(results), encoding="utf-8")

    report = REPORTER.build_report(batch_path)

    aggregate = report["aggregate"]
    assert aggregate["both_passed_count"] == 1
    assert aggregate["baseline_only_passed_count"] == 1
    assert aggregate["treatment_only_passed_count"] == 1
    assert aggregate["both_failed_count"] == 1
    assert "baseline-only **1**; MCP-only **1**; both failed **1**" in REPORTER.render_markdown(report)


def test_acceptance_counts_distinct_repositories_not_repeat_runs(tmp_path: Path) -> None:
    batch_path = _write_run(tmp_path)
    second = tmp_path / "second"
    second.mkdir()
    _write_run(second, benchmark_id="run-b")
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    batch["runs"].append(
        {"benchmark_id": "run-b", "results": "second/results.json", "metadata": "second/metadata.json"}
    )
    batch_path.write_text(json.dumps(batch), encoding="utf-8")

    report = REPORTER.build_report(batch_path)

    assert report["acceptance"]["gates"]["repository_count"]["actual"] == 1
    assert "repository_count" in report["acceptance"]["failed_gates"]


def test_report_allows_same_benchmark_in_independent_repeat(tmp_path: Path) -> None:
    batch_path = _write_run(tmp_path, benchmark_id="click")
    second = tmp_path / "second"
    second.mkdir()
    _write_run(second, benchmark_id="click")
    second_metadata = second / "metadata.json"
    metadata = json.loads(second_metadata.read_text(encoding="utf-8"))
    metadata["repeat_id"] = "repeat-2"
    second_metadata.write_text(json.dumps(metadata), encoding="utf-8")
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    batch["runs"].append(
        {
            "benchmark_id": "click",
            "run_id": "repeat-2",
            "results": "second/results.json",
            "metadata": "second/metadata.json",
        }
    )
    batch_path.write_text(json.dumps(batch), encoding="utf-8")

    report = REPORTER.build_report(batch_path)

    assert len(report["runs"]) == 2
    assert {run["run_id"] for run in report["runs"]} == {"repeat-1", "repeat-2"}
