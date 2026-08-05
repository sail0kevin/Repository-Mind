from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CONTEXT = _load("context_benchmark")
SCORER = _load("score_context_ab_results")
VALIDATOR = _load("validate_context_benchmark")
REPORT = _load("report_external_context_batch")


def _task() -> dict[str, object]:
    return {
        "id": "test-task",
        "category": "change_impact",
        "question": "Explain the behavior and name the implementation, impact, and test files.",
        "required_evidence_groups": [
            [
                {"path": "src/lib/example.ts", "symbol": "primary", "line_start": 10, "line_end": 20},
                {"path": "src/lib/alternative.ts", "symbol": "fallback"},
            ]
        ],
        "required_concept_groups": [["abort", "cancel"], ["safe error"]],
        "required_affected_paths": ["src/app/route.ts"],
        "required_test_paths": ["src/lib/example.test.ts"],
    }


def _answer(*, include_test: bool = True) -> str:
    return json.dumps(
        {
            "evidence": [{"path": "src/lib/example.ts", "symbol": "primary", "line_start": 15, "line_end": 15}],
            "claims": ["The request can abort the operation and emits a safe error."],
            "affected_paths": ["src/app/route.ts"],
            "test_paths": ["src/lib/example.test.ts"] if include_test else [],
            "summary": "The implementation forwards cancellation safely.",
        }
    )


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _create_manifest_fixture(
    tmp_path: Path,
    *,
    evidence: dict[str, object] | None = None,
    required_affected_paths: list[str] | None = None,
    required_test_paths: list[str] | None = None,
    excluded_paths: list[str] | None = None,
) -> Path:
    repository = tmp_path / "repo"
    repository.mkdir()
    src = repository / "src" / "lib"
    app = repository / "src" / "app"
    src.mkdir(parents=True)
    app.mkdir(parents=True)
    (src / "example.ts").write_text("export function primary() {\n  return 'ok';\n}\n", encoding="utf-8")
    (src / "example.test.ts").write_text("test('primary', () => expect(true).toBe(true));\n", encoding="utf-8")
    (app / "route.ts").write_text("export const route = '/fixture';\n", encoding="utf-8")

    subprocess.run(["git", "init"], cwd=repository, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "RepoMind Tests"], cwd=repository, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "tests@example.com"], cwd=repository, check=True, capture_output=True, text=True)
    subprocess.run(["git", "add", "."], cwd=repository, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "fixture"], cwd=repository, check=True, capture_output=True, text=True)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repository, check=True, capture_output=True, text=True).stdout.strip()

    data_dir = tmp_path / "repomind-data"
    data_dir.mkdir()
    database_path = data_dir / "repomind.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE repos (id TEXT PRIMARY KEY)")
        connection.execute("CREATE TABLE repository_snapshots (id TEXT PRIMARY KEY, repo_id TEXT NOT NULL)")
        connection.execute("INSERT INTO repos (id) VALUES (?)", ("repo_fixture",))
        connection.execute("INSERT INTO repository_snapshots (id, repo_id) VALUES (?, ?)", ("snap_fixture", "repo_fixture"))
        connection.commit()

    default_evidence = evidence or {"path": "src/lib/example.ts", "symbol": "primary", "line_start": 1, "line_end": 3}
    task_file = tmp_path / "tasks.json"
    tasks = []
    for category in sorted(CONTEXT.CATEGORIES):
        tasks.append(
            {
                "id": f"{category}-task",
                "category": category,
                "question": f"Fixture question for {category}.",
                "required_evidence_groups": [[default_evidence]],
                "required_concept_groups": [["primary"]],
                "required_affected_paths": required_affected_paths if required_affected_paths is not None else ["src/app/route.ts"],
                "required_test_paths": required_test_paths if required_test_paths is not None else ["src/lib/example.test.ts"],
            }
        )
    holdout = {
        "schema_version": CONTEXT.SCHEMA_VERSION,
        "benchmark_id": "fixture-benchmark",
        "repository_commit": commit,
        "tasks": tasks,
    }
    _write_json(task_file, holdout)

    manifest_path = tmp_path / "manifest.json"
    manifest = {
        "benchmark_id": "fixture-benchmark",
        "repository": {"path": str(repository), "commit": commit},
        "index": {
            "repo_id": "repo_fixture",
            "snapshot_id": "snap_fixture",
            "data_dir": str(data_dir),
            "database_path": str(database_path),
        },
        "task_file": str(task_file),
        "excluded_paths": excluded_paths or [],
    }
    _write_json(manifest_path, manifest)
    return manifest_path


def _write_report_run(
    directory: Path,
    *,
    benchmark_id: str,
    repeat_id: str,
    baseline_passed: bool,
    treatment_passed: bool,
    model: str = "gpt-5.6-terra",
    baseline_infrastructure_failure_class: str | None = None,
    treatment_infrastructure_failure_class: str | None = None,
    baseline_elapsed_ms: int | None = 500,
    treatment_elapsed_ms: int | None = 350,
) -> tuple[str, str]:
    directory.mkdir(parents=True, exist_ok=True)
    results_path = directory / f"{benchmark_id}-{repeat_id}-results.json"
    metadata_path = directory / f"{benchmark_id}-{repeat_id}-metadata.json"
    rows = [
        {
            "task_id": "task-1",
            "mode": "baseline",
            "status": "completed",
            "passed": baseline_passed,
            "failure_class": None if baseline_passed else "rubric_failed",
            "infrastructure_failure_class": baseline_infrastructure_failure_class,
            "input_tokens": 100,
            "cached_input_tokens": 0,
            "output_tokens": 20,
            "source_characters_received": 1000,
            "elapsed_ms": baseline_elapsed_ms,
        },
        {
            "task_id": "task-1",
            "mode": "treatment",
            "status": "completed",
            "passed": treatment_passed,
            "failure_class": None if treatment_passed else "rubric_failed",
            "infrastructure_failure_class": treatment_infrastructure_failure_class,
            "input_tokens": 60,
            "cached_input_tokens": 0,
            "output_tokens": 10,
            "source_characters_received": 400,
            "elapsed_ms": treatment_elapsed_ms,
        },
    ]
    metadata = {
        "benchmark_id": benchmark_id,
        "codex_version": "1.0.0",
        "model": model,
        "reasoning_effort": "high",
        "bypass_sandbox": True,
        "timeout_seconds": 120,
        "mcp_profile": "coding-agent-context",
        "repeat_id": repeat_id,
        "commit": "a" * 40,
        "repository_path": "G:/fixture/repo",
    }
    _write_json(results_path, rows)
    _write_json(metadata_path, metadata)
    return str(results_path), str(metadata_path)


def test_score_context_answer_requires_all_requested_dimensions() -> None:
    result = CONTEXT.score_answer(_task(), _answer())

    assert result["passed"] is True
    assert result["failure_class"] is None
    assert len(result["rubric_checks"]) == 5


def test_score_context_answer_reports_missing_test_target_as_rubric_failure() -> None:
    result = CONTEXT.score_answer(_task(), _answer(include_test=False))

    assert result["passed"] is False
    assert result["failure_class"] == "rubric_failed"
    assert any(check["kind"] == "test_path" and not check["passed"] for check in result["rubric_checks"])


def test_score_context_answer_distinguishes_invalid_json() -> None:
    result = CONTEXT.score_answer(_task(), "not json")

    assert result["passed"] is False
    assert result["failure_class"] == "invalid_structured_answer"
    assert result["rubric_checks"] == []
    assert "not valid JSON" in result["answer_parse_error"]


def test_score_context_answer_accepts_evidence_alternative() -> None:
    answer = json.loads(_answer())
    answer["evidence"] = [{"path": "src/lib/alternative.ts", "symbol": "fallback"}]

    result = CONTEXT.score_answer(_task(), json.dumps(answer))

    assert result["passed"] is True


def test_scorer_requires_complete_paired_matrix(tmp_path: Path) -> None:
    task_file = tmp_path / "tasks.json"
    holdout = {
        "schema_version": CONTEXT.SCHEMA_VERSION,
        "benchmark_id": "fixture",
        "repository_commit": "a" * 40,
        "tasks": [],
    }
    for category in sorted(CONTEXT.CATEGORIES):
        task = _task()
        task["id"] = category
        task["category"] = category
        holdout["tasks"].append(task)
    task_file.write_text(json.dumps(holdout), encoding="utf-8")
    raw = tmp_path / "raw.json"
    raw.write_text(json.dumps([{"task_id": "change_impact", "mode": "baseline", "status": "completed", "answer": _answer()}]), encoding="utf-8")

    with pytest.raises(SCORER.ContextScoringError, match="incomplete"):
        SCORER.score_results(task_file, raw)


def test_scorer_accepts_subset_task_file_for_smoke_runs(tmp_path: Path) -> None:
    task_file = tmp_path / "subset-tasks.json"
    holdout = {
        "schema_version": CONTEXT.SCHEMA_VERSION,
        "benchmark_id": "fixture",
        "repository_commit": "a" * 40,
        "tasks": [_task()],
    }
    task_file.write_text(json.dumps(holdout), encoding="utf-8")
    raw = tmp_path / "raw.json"
    raw.write_text(
        json.dumps(
            [
                {"task_id": "test-task", "mode": "baseline", "status": "completed", "answer": _answer()},
                {"task_id": "test-task", "mode": "treatment", "status": "completed", "answer": _answer()},
            ]
        ),
        encoding="utf-8",
    )

    scored = SCORER.score_results(task_file, raw)

    assert len(scored) == 2
    assert all(row["passed"] is True for row in scored)


@pytest.mark.parametrize(
    ("status", "mcp_tool_call_count", "final_answer_present", "expected"),
    [
        ("timeout", 0, False, "timeout_before_mcp_call"),
        ("timeout", 1, False, "timeout_after_mcp_before_final_answer"),
        ("incomplete", 1, False, "incomplete_after_mcp_before_final_answer"),
        ("incomplete", 0, False, "incomplete_before_mcp_call"),
    ],
)
def test_scorer_infers_stage_specific_incomplete_failure_class(
    tmp_path: Path,
    status: str,
    mcp_tool_call_count: int,
    final_answer_present: bool,
    expected: str,
) -> None:
    task_file = tmp_path / "tasks.json"
    task_file.write_text(
        json.dumps(
            {
                "schema_version": CONTEXT.SCHEMA_VERSION,
                "benchmark_id": "fixture",
                "repository_commit": "a" * 40,
                "tasks": [_task()],
            }
        ),
        encoding="utf-8",
    )
    raw = tmp_path / "raw.json"
    rows = [
        {
            "task_id": "test-task",
            "mode": "baseline",
            "status": status,
            "mcp_tool_call_count": mcp_tool_call_count,
            "final_answer_present": final_answer_present,
        },
        {"task_id": "test-task", "mode": "treatment", "status": "completed", "answer": _answer()},
    ]
    raw.write_text(json.dumps(rows), encoding="utf-8")

    scored = SCORER.score_results(task_file, raw)

    assert scored[0]["passed"] is False
    assert scored[0]["failure_class"] == expected


def test_scorer_preserves_runner_failure_class(tmp_path: Path) -> None:
    task_file = tmp_path / "tasks.json"
    task_file.write_text(
        json.dumps(
            {
                "schema_version": CONTEXT.SCHEMA_VERSION,
                "benchmark_id": "fixture",
                "repository_commit": "a" * 40,
                "tasks": [_task()],
            }
        ),
        encoding="utf-8",
    )
    raw = tmp_path / "raw.json"
    raw.write_text(
        json.dumps(
            [
                {
                    "task_id": "test-task",
                    "mode": "baseline",
                    "status": "incomplete",
                    "failure_class": "runner_specific_failure",
                    "mcp_tool_call_count": 0,
                },
                {"task_id": "test-task", "mode": "treatment", "status": "completed", "answer": _answer()},
            ]
        ),
        encoding="utf-8",
    )

    scored = SCORER.score_results(task_file, raw)

    assert scored[0]["failure_class"] == "runner_specific_failure"


def test_validate_manifest_rejects_out_of_range_evidence_span(tmp_path: Path) -> None:
    manifest_path = _create_manifest_fixture(
        tmp_path,
        evidence={"path": "src/lib/example.ts", "symbol": "primary", "line_start": 1, "line_end": 9},
    )

    with pytest.raises(VALIDATOR.ContextBenchmarkValidationError, match="out-of-range evidence span"):
        VALIDATOR.validate_manifest(manifest_path)


def test_validate_manifest_reads_index_through_immutable_sqlite_connection(tmp_path: Path) -> None:
    manifest_path = _create_manifest_fixture(tmp_path)

    result = VALIDATOR.validate_manifest(manifest_path)

    assert result["repo_id"] == "repo_fixture"
    assert result["snapshot_id"] == "snap_fixture"


def test_validate_manifest_rejects_missing_symbol_text(tmp_path: Path) -> None:
    manifest_path = _create_manifest_fixture(
        tmp_path,
        evidence={"path": "src/lib/example.ts", "symbol": "missingSymbol", "line_start": 1, "line_end": 3},
    )

    with pytest.raises(VALIDATOR.ContextBenchmarkValidationError, match="symbol 'missingSymbol'"):
        VALIDATOR.validate_manifest(manifest_path)


@pytest.mark.parametrize(
    ("field", "paths", "excluded", "expected_fragment"),
    [
        ("required_test_paths", ["src/lib/example.test.ts"], ["src/lib/example.test.ts"], "excluded required_test_paths path"),
        ("required_affected_paths", ["src/app/route.ts"], ["src/app"], "excluded required_affected_paths path"),
    ],
)
def test_validate_manifest_rejects_excluded_required_paths(
    tmp_path: Path,
    field: str,
    paths: list[str],
    excluded: list[str],
    expected_fragment: str,
) -> None:
    kwargs = {
        "required_test_paths": [] if field == "required_affected_paths" else paths,
        "required_affected_paths": [] if field == "required_test_paths" else paths,
        "excluded_paths": excluded,
    }
    manifest_path = _create_manifest_fixture(tmp_path, **kwargs)

    with pytest.raises(VALIDATOR.ContextBenchmarkValidationError, match=expected_fragment):
        VALIDATOR.validate_manifest(manifest_path)


def test_build_report_aggregates_paired_runs_and_accepts(tmp_path: Path) -> None:
    runs = []
    for repeat_id in ("repeat-1", "repeat-2"):
        results, metadata = _write_report_run(
            tmp_path,
            benchmark_id="fixture-benchmark",
            repeat_id=repeat_id,
            baseline_passed=True,
            treatment_passed=True,
        )
        runs.append({"benchmark_id": "fixture-benchmark", "results": results, "metadata": metadata})
    batch_path = tmp_path / "batch.json"
    _write_json(
        batch_path,
        {
            "batch_id": "fixture-batch",
            "acceptance": {"min_task_count": 1, "min_independent_repeats": 2},
            "runs": runs,
        },
    )

    report = REPORT.build_report(batch_path)

    assert report["aggregate"]["task_count"] == 2
    assert report["aggregate"]["both_passed_count"] == 2
    assert report["aggregate"]["input_tokens_saving_percent"] == 40.0
    assert report["aggregate"]["total_tokens_saving_percent"] == 41.67
    assert report["aggregate"]["source_characters_saving_percent"] == 60.0
    assert report["cost_comparison"] == {
        "task_count": 2,
        "evaluable_task_count": 2,
        "paired_cost_task_count": 2,
        "both_passed_count": 2,
        "baseline_only_passed_count": 0,
        "treatment_only_passed_count": 0,
        "both_failed_count": 0,
        "infrastructure_excluded_task_count": 0,
        "token_totals_include": "Only paired tasks passed by both baseline and treatment.",
        "token_totals_exclude": (
            "Infrastructure failures and evaluable tasks not passed by both cohorts are excluded from "
            "token, source-character, and latency totals."
        ),
        "denominator_description": (
            "Saving percentages use the baseline total over paired tasks passed by both cohorts as the "
            "denominator; pass rates use evaluable paired tasks as the denominator."
        ),
    }
    assert report["acceptance"]["status"] == "accepted"
    assert report["condition_mismatches"] == {}


def test_build_report_cost_totals_use_only_both_passed_tasks(tmp_path: Path) -> None:
    results, metadata = _write_report_run(
        tmp_path,
        benchmark_id="fixture-benchmark",
        repeat_id="repeat-1",
        baseline_passed=True,
        treatment_passed=False,
    )
    batch_path = tmp_path / "batch.json"
    _write_json(
        batch_path,
        {
            "batch_id": "fixture-batch",
            "acceptance": {"min_task_count": 1, "min_independent_repeats": 1},
            "runs": [{"benchmark_id": "fixture-benchmark", "results": results, "metadata": metadata}],
        },
    )

    report = REPORT.build_report(batch_path)

    aggregate = report["aggregate"]
    assert aggregate["task_count"] == 1
    assert aggregate["evaluable_task_count"] == 1
    assert aggregate["both_passed_count"] == 0
    assert aggregate["cost_comparison_task_count"] == 0
    assert aggregate["baseline_input_tokens"] == 0
    assert aggregate["treatment_input_tokens"] == 0
    assert aggregate["input_tokens_saving_percent"] is None
    assert report["cost_comparison"]["paired_cost_task_count"] == 0


def test_build_report_marks_latency_incomparable_when_one_paired_observation_is_missing(
    tmp_path: Path,
) -> None:
    results, metadata = _write_report_run(
        tmp_path,
        benchmark_id="fixture-benchmark",
        repeat_id="repeat-1",
        baseline_passed=True,
        treatment_passed=True,
        treatment_elapsed_ms=None,
    )
    batch_path = tmp_path / "batch.json"
    _write_json(
        batch_path,
        {
            "batch_id": "fixture-batch",
            "acceptance": {"min_task_count": 1, "min_independent_repeats": 1},
            "runs": [{"benchmark_id": "fixture-benchmark", "results": results, "metadata": metadata}],
        },
    )

    report = REPORT.build_report(batch_path)

    aggregate = report["aggregate"]
    assert aggregate["elapsed_ms_comparable"] is False
    assert aggregate["elapsed_ms_saved"] is None
    assert aggregate["elapsed_ms_saving_percent"] is None


def test_render_markdown_exposes_task_and_token_denominators(tmp_path: Path) -> None:
    results, metadata = _write_report_run(
        tmp_path,
        benchmark_id="fixture-benchmark",
        repeat_id="repeat-1",
        baseline_passed=True,
        treatment_passed=True,
    )
    batch_path = tmp_path / "batch.json"
    _write_json(
        batch_path,
        {
            "batch_id": "fixture-batch",
            "acceptance": {"min_task_count": 1, "min_independent_repeats": 1},
            "runs": [{"benchmark_id": "fixture-benchmark", "results": results, "metadata": metadata}],
        },
    )

    rendered = REPORT.render_markdown(REPORT.build_report(batch_path))

    assert "Total paired tasks: **1**" in rendered
    assert "Evaluable paired tasks: **1**" in rendered
    assert "Paired cost-comparison tasks: **1**" in rendered
    assert "Only paired tasks passed by both baseline and treatment." in rendered


def test_build_report_excludes_infrastructure_failures_from_evaluation_and_costs(tmp_path: Path) -> None:
    successful_results, successful_metadata = _write_report_run(
        tmp_path,
        benchmark_id="fixture-benchmark",
        repeat_id="repeat-1",
        baseline_passed=True,
        treatment_passed=True,
    )
    infrastructure_results, infrastructure_metadata = _write_report_run(
        tmp_path,
        benchmark_id="fixture-benchmark",
        repeat_id="repeat-2",
        baseline_passed=False,
        treatment_passed=False,
        baseline_infrastructure_failure_class="provider_network_unavailable",
        treatment_infrastructure_failure_class="provider_network_unavailable",
    )
    batch_path = tmp_path / "batch.json"
    _write_json(
        batch_path,
        {
            "batch_id": "fixture-batch",
            "acceptance": {"min_task_count": 1, "min_independent_repeats": 2},
            "runs": [
                {"benchmark_id": "fixture-benchmark", "results": successful_results, "metadata": successful_metadata},
                {
                    "benchmark_id": "fixture-benchmark",
                    "results": infrastructure_results,
                    "metadata": infrastructure_metadata,
                },
            ],
        },
    )

    report = REPORT.build_report(batch_path)
    aggregate = report["aggregate"]

    assert aggregate["task_count"] == 2
    assert aggregate["evaluable_task_count"] == 1
    assert aggregate["infrastructure_excluded_task_count"] == 1
    assert aggregate["baseline_passed"] == 1
    assert aggregate["treatment_passed"] == 1
    assert aggregate["baseline_pass_rate"] == 1.0
    assert aggregate["treatment_pass_rate"] == 1.0
    assert aggregate["input_tokens_saving_percent"] == 40.0
    assert report["infrastructure_failure_classes"] == {"provider_network_unavailable": 2}
    assert report["infrastructure_failure_classes_by_cohort"] == {
        "baseline": {"provider_network_unavailable": 1},
        "treatment": {"provider_network_unavailable": 1},
    }
    assert report["acceptance"]["status"] == "not_accepted"
    assert report["acceptance"]["failed_gates"] == ["independent_repeats"]
    assert report["acceptance"]["repeat_ids"] == ["repeat-1", "repeat-2"]
    assert report["acceptance"]["evaluable_repeat_ids"] == ["repeat-1"]
    assert report["acceptance"]["evaluable_independent_repeats"] == 1
    assert report["acceptance"]["gates"]["task_count"]["actual"] == 1


def test_build_report_does_not_report_zero_pass_rate_when_all_tasks_are_infrastructure_failures(
    tmp_path: Path,
) -> None:
    runs = []
    for repeat_id in ("repeat-1", "repeat-2"):
        results, metadata = _write_report_run(
            tmp_path,
            benchmark_id="fixture-benchmark",
            repeat_id=repeat_id,
            baseline_passed=False,
            treatment_passed=False,
            baseline_infrastructure_failure_class="provider_network_unavailable",
            treatment_infrastructure_failure_class="provider_network_unavailable",
        )
        runs.append({"benchmark_id": "fixture-benchmark", "results": results, "metadata": metadata})
    batch_path = tmp_path / "batch.json"
    _write_json(
        batch_path,
        {
            "batch_id": "fixture-batch",
            "acceptance": {"min_task_count": 1, "min_independent_repeats": 2},
            "runs": runs,
        },
    )

    report = REPORT.build_report(batch_path)
    aggregate = report["aggregate"]

    assert aggregate["task_count"] == 2
    assert aggregate["evaluable_task_count"] == 0
    assert aggregate["infrastructure_excluded_task_count"] == 2
    assert aggregate["baseline_pass_rate"] is None
    assert aggregate["treatment_pass_rate"] is None
    assert aggregate["input_tokens_saving_percent"] is None
    assert report["acceptance"]["status"] == "not_accepted"
    assert report["acceptance"]["failed_gates"] == [
        "task_count",
        "independent_repeats",
        "treatment_pass_rate",
    ]
    assert report["acceptance"]["evaluable_repeat_ids"] == []
    assert report["acceptance"]["evaluable_independent_repeats"] == 0


def test_build_report_flags_mismatched_conditions(tmp_path: Path) -> None:
    first_results, first_metadata = _write_report_run(
        tmp_path,
        benchmark_id="fixture-benchmark",
        repeat_id="repeat-1",
        baseline_passed=True,
        treatment_passed=True,
        model="gpt-5.6-terra",
    )
    second_results, second_metadata = _write_report_run(
        tmp_path,
        benchmark_id="fixture-benchmark",
        repeat_id="repeat-2",
        baseline_passed=True,
        treatment_passed=True,
        model="gpt-5.6-luna",
    )
    batch_path = tmp_path / "batch.json"
    _write_json(
        batch_path,
        {
            "batch_id": "fixture-batch",
            "acceptance": {"min_task_count": 1, "min_independent_repeats": 2},
            "runs": [
                {"benchmark_id": "fixture-benchmark", "results": first_results, "metadata": first_metadata},
                {"benchmark_id": "fixture-benchmark", "results": second_results, "metadata": second_metadata},
            ],
        },
    )

    report = REPORT.build_report(batch_path)

    assert report["condition_mismatches"] == {"model": ["gpt-5.6-luna", "gpt-5.6-terra"]}
    assert report["acceptance"]["status"] == "not_accepted"
    assert report["acceptance"]["failed_gates"] == ["identical_conditions"]


def test_build_report_requires_multiple_independent_repeats(tmp_path: Path) -> None:
    results, metadata = _write_report_run(
        tmp_path,
        benchmark_id="fixture-benchmark",
        repeat_id="repeat-1",
        baseline_passed=True,
        treatment_passed=True,
    )
    batch_path = tmp_path / "batch.json"
    _write_json(
        batch_path,
        {
            "batch_id": "fixture-batch",
            "acceptance": {"min_task_count": 1, "min_independent_repeats": 2},
            "runs": [{"benchmark_id": "fixture-benchmark", "results": results, "metadata": metadata}],
        },
    )

    report = REPORT.build_report(batch_path)

    assert report["acceptance"]["status"] == "not_accepted"
    assert report["acceptance"]["failed_gates"] == ["independent_repeats"]


def test_context_runner_keeps_single_mode_runs_out_of_paired_scoring() -> None:
    runner = (SCRIPTS / "run_codex_context_ab.ps1").read_text(encoding="utf-8")

    assert "foreach ($runMode in $selectedModes)" in runner
    assert "$isPairedRun = $Mode -eq \"all\"" in runner
    assert "if ($isPairedRun)" in runner
    assert "partial-results-$Mode.json" in runner
    assert '$scoringStatus = "not_run_single_mode"' in runner
    assert "modes = @($selectedModes)" in runner
