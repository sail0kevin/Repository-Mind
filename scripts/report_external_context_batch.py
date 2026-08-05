"""Aggregate isolated RepoMind external context A/B benchmark runs.

The report separates pass-rate outcomes from token/context deltas. Cost comparisons
use only tasks passed by both cohorts so a cheaper failure never looks like a win.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


class ContextBatchReportError(RuntimeError):
    """Raised when context benchmark outputs cannot support an auditable report."""


COMPARABLE_FIELDS = (
    "codex_version",
    "model",
    "reasoning_effort",
    "bypass_sandbox",
    "timeout_seconds",
    "mcp_profile",
    "benchmark_id",
    "commit",
)
DEFAULT_ACCEPTANCE = {
    "min_task_count": 5,
    "min_independent_repeats": 2,
    "require_treatment_pass_rate_at_least_baseline": True,
    "require_identical_conditions": True,
}
INFRASTRUCTURE_FAILURE_FIELD = "infrastructure_failure_class"


def _read_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContextBatchReportError(f"Cannot read {label} at {path}: {exc}") from exc


def _read_object(path: Path, label: str) -> dict[str, Any]:
    payload = _read_json(path, label)
    if not isinstance(payload, dict):
        raise ContextBatchReportError(f"{label} at {path} must be a JSON object.")
    return payload


def _resolve(base: Path, raw: object, label: str) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise ContextBatchReportError(f"{label} must be a non-empty path string.")
    path = Path(raw).expanduser()
    resolved = path.resolve() if path.is_absolute() else (base / path).resolve()
    if not resolved.is_file():
        raise ContextBatchReportError(f"{label} does not exist: {resolved}")
    return resolved


def _percent_saving(baseline: int, treatment: int) -> float | None:
    if baseline <= 0:
        return None
    return round((baseline - treatment) * 100 / baseline, 2)


def _add_cost_fields(values: dict[str, Any]) -> None:
    for cohort in ("baseline", "treatment"):
        values[f"{cohort}_total_tokens"] = values[f"{cohort}_input_tokens"] + values[f"{cohort}_output_tokens"]
    for metric in ("input_tokens", "output_tokens", "total_tokens", "source_characters"):
        baseline = values[f"baseline_{metric}"]
        treatment = values[f"treatment_{metric}"]
        values[f"{metric}_saved"] = baseline - treatment
        values[f"{metric}_saving_percent"] = _percent_saving(baseline, treatment)
    elapsed_is_comparable = all(
        values.get(f"{cohort}_elapsed_ms_observations", 0) == values.get("cost_comparison_task_count", 0)
        for cohort in ("baseline", "treatment")
    )
    values["elapsed_ms_comparable"] = elapsed_is_comparable
    if elapsed_is_comparable:
        values["elapsed_ms_saved"] = values["baseline_elapsed_ms"] - values["treatment_elapsed_ms"]
        values["elapsed_ms_saving_percent"] = _percent_saving(
            values["baseline_elapsed_ms"], values["treatment_elapsed_ms"]
        )
    else:
        values["elapsed_ms_saved"] = None
        values["elapsed_ms_saving_percent"] = None


def _load_run(entry: dict[str, Any], base: Path) -> dict[str, Any]:
    benchmark_id = entry.get("benchmark_id")
    if not isinstance(benchmark_id, str) or not benchmark_id.strip():
        raise ContextBatchReportError("Every batch run needs a non-empty benchmark_id.")
    results_path = _resolve(base, entry.get("results"), f"run {benchmark_id}.results")
    metadata_path = _resolve(base, entry.get("metadata"), f"run {benchmark_id}.metadata")
    rows = _read_json(results_path, f"results for {benchmark_id}")
    metadata = _read_object(metadata_path, f"metadata for {benchmark_id}")
    if not isinstance(rows, list) or not rows:
        raise ContextBatchReportError(f"Results for {benchmark_id} must be a non-empty JSON array.")
    if metadata.get("benchmark_id") != benchmark_id:
        raise ContextBatchReportError(f"Metadata benchmark_id does not match batch entry for {benchmark_id}.")

    missing_conditions = [field for field in COMPARABLE_FIELDS if metadata.get(field) in (None, "")]
    if missing_conditions:
        raise ContextBatchReportError(
            f"Metadata for {benchmark_id} lacks comparable conditions: {', '.join(missing_conditions)}."
        )

    by_task: dict[str, dict[str, dict[str, Any]]] = {}
    failure_classes: dict[str, int] = {}
    failure_classes_by_cohort: dict[str, dict[str, int]] = {"baseline": {}, "treatment": {}}
    infrastructure_failure_classes: dict[str, int] = {}
    infrastructure_failure_classes_by_cohort: dict[str, dict[str, int]] = {"baseline": {}, "treatment": {}}
    statuses: dict[str, int] = {}
    statuses_by_cohort: dict[str, dict[str, int]] = {"baseline": {}, "treatment": {}}
    for row in rows:
        if not isinstance(row, dict):
            raise ContextBatchReportError(f"Results for {benchmark_id} contain a non-object row.")
        task_id, mode = row.get("task_id"), row.get("mode")
        if not isinstance(task_id, str) or not task_id.strip() or mode not in {"baseline", "treatment"}:
            raise ContextBatchReportError(f"Results for {benchmark_id} contain an invalid task_id or mode.")
        task = by_task.setdefault(task_id, {})
        if mode in task:
            raise ContextBatchReportError(f"Results for {benchmark_id} contain duplicate {mode}/{task_id} rows.")
        if not isinstance(row.get("passed"), bool):
            raise ContextBatchReportError(f"Results for {benchmark_id} have invalid passed for {mode}/{task_id}.")
        for field in ("input_tokens", "cached_input_tokens", "output_tokens", "source_characters_received"):
            if not isinstance(row.get(field), int) or row[field] < 0:
                raise ContextBatchReportError(f"Results for {benchmark_id} have invalid {field} for {mode}/{task_id}.")
        elapsed_ms = row.get("elapsed_ms")
        if elapsed_ms is not None and (not isinstance(elapsed_ms, int) or isinstance(elapsed_ms, bool) or elapsed_ms < 0):
            raise ContextBatchReportError(f"Results for {benchmark_id} have invalid elapsed_ms for {mode}/{task_id}.")
        status = row.get("status")
        if not isinstance(status, str) or not status:
            raise ContextBatchReportError(f"Results for {benchmark_id} have invalid status for {mode}/{task_id}.")
        statuses[status] = statuses.get(status, 0) + 1
        statuses_by_cohort[mode][status] = statuses_by_cohort[mode].get(status, 0) + 1
        failure_class = row.get("failure_class")
        if failure_class:
            if not isinstance(failure_class, str):
                raise ContextBatchReportError(f"Results for {benchmark_id} have invalid failure_class for {mode}/{task_id}.")
            failure_classes[failure_class] = failure_classes.get(failure_class, 0) + 1
            failure_classes_by_cohort[mode][failure_class] = failure_classes_by_cohort[mode].get(failure_class, 0) + 1
        infrastructure_failure_class = row.get(INFRASTRUCTURE_FAILURE_FIELD)
        if infrastructure_failure_class not in (None, ""):
            if not isinstance(infrastructure_failure_class, str):
                raise ContextBatchReportError(
                    f"Results for {benchmark_id} have invalid {INFRASTRUCTURE_FAILURE_FIELD} "
                    f"for {mode}/{task_id}."
                )
            infrastructure_failure_classes[infrastructure_failure_class] = (
                infrastructure_failure_classes.get(infrastructure_failure_class, 0) + 1
            )
            infrastructure_failure_classes_by_cohort[mode][infrastructure_failure_class] = (
                infrastructure_failure_classes_by_cohort[mode].get(infrastructure_failure_class, 0) + 1
            )
        task[mode] = row
    incomplete = sorted(task_id for task_id, task in by_task.items() if set(task) != {"baseline", "treatment"})
    if incomplete:
        raise ContextBatchReportError(f"Results for {benchmark_id} lack one cohort for: {', '.join(incomplete)}.")
    return {
        "benchmark_id": benchmark_id,
        "run_id": str(metadata.get("repeat_id") or entry.get("run_id") or "repeat-1"),
        "metadata": metadata,
        "tasks": by_task,
        "failure_classes": failure_classes,
        "failure_classes_by_cohort": failure_classes_by_cohort,
        "infrastructure_failure_classes": infrastructure_failure_classes,
        "infrastructure_failure_classes_by_cohort": infrastructure_failure_classes_by_cohort,
        "statuses": statuses,
        "statuses_by_cohort": statuses_by_cohort,
    }


def _acceptance_config(batch: dict[str, Any]) -> dict[str, Any]:
    raw = batch.get("acceptance")
    if raw is None:
        return dict(DEFAULT_ACCEPTANCE)
    if not isinstance(raw, dict):
        raise ContextBatchReportError("batch config.acceptance must be an object.")
    config = dict(DEFAULT_ACCEPTANCE)
    config.update(raw)
    if not isinstance(config["min_task_count"], int) or config["min_task_count"] < 1:
        raise ContextBatchReportError("acceptance.min_task_count must be a positive integer.")
    if not isinstance(config["min_independent_repeats"], int) or config["min_independent_repeats"] < 1:
        raise ContextBatchReportError("acceptance.min_independent_repeats must be a positive integer.")
    for field in ("require_treatment_pass_rate_at_least_baseline", "require_identical_conditions"):
        if not isinstance(config[field], bool):
            raise ContextBatchReportError(f"acceptance.{field} must be boolean.")
    return config


def _is_evaluable_task(task: dict[str, dict[str, Any]]) -> bool:
    """Return whether a paired task is usable for product evaluation."""
    return not any(
        row.get(INFRASTRUCTURE_FAILURE_FIELD) not in (None, "")
        for row in task.values()
    )


def _evaluable_task_count(run: dict[str, Any]) -> int:
    return sum(1 for task in run["tasks"].values() if _is_evaluable_task(task))


def _evaluate_acceptance(
    *,
    batch: dict[str, Any],
    loaded: list[dict[str, Any]],
    aggregate: dict[str, Any],
    condition_mismatches: dict[str, list[str]],
) -> dict[str, Any]:
    config = _acceptance_config(batch)
    repeat_ids = {str(run["run_id"]) for run in loaded}
    evaluable_repeat_ids = {
        str(run["run_id"])
        for run in loaded
        if _evaluable_task_count(run) > 0
    }
    gates: dict[str, dict[str, Any]] = {
        "task_count": {
            "actual": aggregate["evaluable_task_count"],
            "minimum": config["min_task_count"],
            "passed": aggregate["evaluable_task_count"] >= config["min_task_count"],
        },
        "independent_repeats": {
            "actual": len(evaluable_repeat_ids),
            "minimum": config["min_independent_repeats"],
            "passed": len(evaluable_repeat_ids) >= config["min_independent_repeats"],
        },
    }
    if config["require_treatment_pass_rate_at_least_baseline"]:
        gates["treatment_pass_rate"] = {
            "actual": aggregate["treatment_pass_rate"],
            "minimum": aggregate["baseline_pass_rate"],
            "passed": (
                aggregate["treatment_pass_rate"] is not None
                and aggregate["baseline_pass_rate"] is not None
                and aggregate["treatment_pass_rate"] >= aggregate["baseline_pass_rate"]
            ),
        }
    if config["require_identical_conditions"]:
        gates["identical_conditions"] = {
            "actual": condition_mismatches,
            "minimum": {},
            "passed": not condition_mismatches,
        }
    failed = [name for name, gate in gates.items() if not gate["passed"]]
    return {
        "status": "accepted" if not failed else "not_accepted",
        "failed_gates": failed,
        "config": config,
        "repeat_ids": sorted(repeat_ids),
        "evaluable_repeat_ids": sorted(evaluable_repeat_ids),
        "evaluable_independent_repeats": len(evaluable_repeat_ids),
        "gates": gates,
    }


def build_report(batch_path: Path) -> dict[str, Any]:
    batch = _read_object(batch_path, "batch config")
    runs = batch.get("runs")
    if not isinstance(runs, list) or not runs:
        raise ContextBatchReportError("batch config.runs must be a non-empty array.")
    if any(not isinstance(entry, dict) for entry in runs):
        raise ContextBatchReportError("Every batch run must be an object.")
    loaded = [_load_run(entry, batch_path.parent) for entry in runs]
    identifiers = [(run["benchmark_id"], run["run_id"]) for run in loaded]
    if len(set(identifiers)) != len(identifiers):
        raise ContextBatchReportError("batch config contains duplicate benchmark_id/run_id values.")

    condition_mismatches: dict[str, list[str]] = {}
    for field in COMPARABLE_FIELDS:
        values = {str(run["metadata"].get(field)) for run in loaded}
        if len(values) != 1:
            condition_mismatches[field] = sorted(values)

    totals: dict[str, Any] = {
        "task_count": 0,
        "evaluable_task_count": 0,
        "infrastructure_excluded_task_count": 0,
        "baseline_passed": 0,
        "treatment_passed": 0,
        "both_passed_count": 0,
        "cost_comparison_task_count": 0,
        "baseline_only_passed_count": 0,
        "treatment_only_passed_count": 0,
        "both_failed_count": 0,
        "baseline_input_tokens": 0,
        "treatment_input_tokens": 0,
        "baseline_output_tokens": 0,
        "treatment_output_tokens": 0,
        "baseline_source_characters": 0,
        "treatment_source_characters": 0,
        "baseline_elapsed_ms": 0,
        "treatment_elapsed_ms": 0,
        "baseline_elapsed_ms_observations": 0,
        "treatment_elapsed_ms_observations": 0,
    }
    per_run: list[dict[str, Any]] = []
    failure_classes: dict[str, int] = {}
    failure_classes_by_cohort: dict[str, dict[str, int]] = {"baseline": {}, "treatment": {}}
    infrastructure_failure_classes: dict[str, int] = {}
    infrastructure_failure_classes_by_cohort: dict[str, dict[str, int]] = {"baseline": {}, "treatment": {}}
    statuses: dict[str, int] = {}
    statuses_by_cohort: dict[str, dict[str, int]] = {"baseline": {}, "treatment": {}}
    for run in loaded:
        run_totals = {key: 0 for key in totals}
        for task in run["tasks"].values():
            baseline, treatment = task["baseline"], task["treatment"]
            for values in (totals, run_totals):
                values["task_count"] += 1
            has_infrastructure_failure = not _is_evaluable_task(task)
            if has_infrastructure_failure:
                for values in (totals, run_totals):
                    values["infrastructure_excluded_task_count"] += 1
                continue
            for values in (totals, run_totals):
                values["evaluable_task_count"] += 1
                values["baseline_passed"] += int(baseline["passed"])
                values["treatment_passed"] += int(treatment["passed"])
            if baseline["passed"] and treatment["passed"]:
                for values in (totals, run_totals):
                    values["both_passed_count"] += 1
                    values["cost_comparison_task_count"] += 1
                    for cohort, row in (("baseline", baseline), ("treatment", treatment)):
                        values[f"{cohort}_input_tokens"] += row["input_tokens"]
                        values[f"{cohort}_output_tokens"] += row["output_tokens"]
                        values[f"{cohort}_source_characters"] += row["source_characters_received"]
                        elapsed_ms = row.get("elapsed_ms")
                        if elapsed_ms is not None:
                            values[f"{cohort}_elapsed_ms"] += elapsed_ms
                            values[f"{cohort}_elapsed_ms_observations"] += 1
            elif baseline["passed"]:
                for values in (totals, run_totals):
                    values["baseline_only_passed_count"] += 1
            elif treatment["passed"]:
                for values in (totals, run_totals):
                    values["treatment_only_passed_count"] += 1
            else:
                for values in (totals, run_totals):
                    values["both_failed_count"] += 1
        for values in (run_totals,):
            denominator = values["evaluable_task_count"]
            values["baseline_pass_rate"] = (
                round(values["baseline_passed"] / denominator, 4) if denominator else None
            )
            values["treatment_pass_rate"] = (
                round(values["treatment_passed"] / denominator, 4) if denominator else None
            )
            _add_cost_fields(values)
        per_run.append(
            {
                "benchmark_id": run["benchmark_id"],
                "run_id": run["run_id"],
                "commit": run["metadata"]["commit"],
                "repository_path": run["metadata"].get("repository_path"),
                **run_totals,
            }
        )
        for name, count in run["failure_classes"].items():
            failure_classes[name] = failure_classes.get(name, 0) + count
        for cohort, cohort_counts in run["failure_classes_by_cohort"].items():
            for name, count in cohort_counts.items():
                failure_classes_by_cohort[cohort][name] = failure_classes_by_cohort[cohort].get(name, 0) + count
        for name, count in run["infrastructure_failure_classes"].items():
            infrastructure_failure_classes[name] = infrastructure_failure_classes.get(name, 0) + count
        for cohort, cohort_counts in run["infrastructure_failure_classes_by_cohort"].items():
            for name, count in cohort_counts.items():
                infrastructure_failure_classes_by_cohort[cohort][name] = (
                    infrastructure_failure_classes_by_cohort[cohort].get(name, 0) + count
                )
        for name, count in run["statuses"].items():
            statuses[name] = statuses.get(name, 0) + count
        for cohort, cohort_counts in run["statuses_by_cohort"].items():
            for name, count in cohort_counts.items():
                statuses_by_cohort[cohort][name] = statuses_by_cohort[cohort].get(name, 0) + count

    denominator = totals["evaluable_task_count"]
    totals["baseline_pass_rate"] = round(totals["baseline_passed"] / denominator, 4) if denominator else None
    totals["treatment_pass_rate"] = round(totals["treatment_passed"] / denominator, 4) if denominator else None
    _add_cost_fields(totals)
    cost_comparison = {
        "task_count": totals["task_count"],
        "evaluable_task_count": totals["evaluable_task_count"],
        "paired_cost_task_count": totals["cost_comparison_task_count"],
        "both_passed_count": totals["both_passed_count"],
        "baseline_only_passed_count": totals["baseline_only_passed_count"],
        "treatment_only_passed_count": totals["treatment_only_passed_count"],
        "both_failed_count": totals["both_failed_count"],
        "infrastructure_excluded_task_count": totals["infrastructure_excluded_task_count"],
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
    report = {
        "schema_version": "repomind-context-batch-report-v2",
        "batch_id": batch.get("batch_id") or batch_path.stem,
        "conditions": {field: loaded[0]["metadata"][field] for field in COMPARABLE_FIELDS},
        "condition_mismatches": condition_mismatches,
        "comparison_rule": (
            "Infrastructure failures remain in task_count but are excluded from evaluable_task_count, "
            "pass-rate denominators, and paired cost comparisons. Token, source-character, and latency "
            "totals include only tasks passed by both cohorts."
        ),
        "aggregate": totals,
        "cost_comparison": cost_comparison,
        "runs": per_run,
        "failure_classes": failure_classes,
        "failure_classes_by_cohort": failure_classes_by_cohort,
        "infrastructure_failure_classes": infrastructure_failure_classes,
        "infrastructure_failure_classes_by_cohort": infrastructure_failure_classes_by_cohort,
        "statuses": statuses,
        "statuses_by_cohort": statuses_by_cohort,
    }
    report["acceptance"] = _evaluate_acceptance(
        batch=batch,
        loaded=loaded,
        aggregate=totals,
        condition_mismatches=condition_mismatches,
    )
    return report


def render_markdown(report: dict[str, Any]) -> str:
    """Render the auditable comparison fields without hiding their denominators."""
    aggregate = report["aggregate"]
    comparison = report["cost_comparison"]
    acceptance = report["acceptance"]
    task_count = aggregate["evaluable_task_count"]
    baseline_rate = aggregate["baseline_pass_rate"]
    treatment_rate = aggregate["treatment_pass_rate"]

    lines = [
        f"# RepoMind Context A/B Report: {report['batch_id']}",
        "",
        f"- Acceptance: **{acceptance['status']}**",
        f"- Total paired tasks: **{comparison['task_count']}**",
        f"- Evaluable paired tasks: **{comparison['evaluable_task_count']}**",
        f"- Infrastructure-excluded tasks: **{comparison['infrastructure_excluded_task_count']}**",
        f"- Baseline pass rate: **{baseline_rate if baseline_rate is not None else 'N/A'}** ({aggregate['baseline_passed']}/{task_count})",
        f"- Treatment pass rate: **{treatment_rate if treatment_rate is not None else 'N/A'}** ({aggregate['treatment_passed']}/{task_count})",
        f"- Paired cost-comparison tasks: **{comparison['paired_cost_task_count']}**",
        "",
        "## Token Comparison",
        "",
        f"- Input tokens: `{aggregate['baseline_input_tokens']}` -> `{aggregate['treatment_input_tokens']}` ({aggregate['input_tokens_saving_percent']}% saved)",
        f"- Total tokens: `{aggregate['baseline_total_tokens']}` -> `{aggregate['treatment_total_tokens']}` ({aggregate['total_tokens_saving_percent']}% saved)",
        "",
        f"> {comparison['denominator_description']}",
        f"> {comparison['token_totals_include']}",
        f"> {comparison['token_totals_exclude']}",
        "",
    ]
    if acceptance["failed_gates"]:
        lines.append(f"- Failed acceptance gates: `{', '.join(acceptance['failed_gates'])}`")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", required=True, type=Path, help="JSON file listing result/metadata pairs.")
    parser.add_argument("--output", type=Path, help="Optional JSON report path; otherwise print to stdout.")
    parser.add_argument("--markdown-output", type=Path, help="Optional human-readable Markdown report path.")
    args = parser.parse_args()
    try:
        report = build_report(args.batch.resolve())
    except ContextBatchReportError as exc:
        print(f"Context batch report failed: {exc}")
        return 2
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    if args.markdown_output:
        args.markdown_output.write_text(render_markdown(report) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
