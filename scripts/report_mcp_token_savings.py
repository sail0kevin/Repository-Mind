"""Report paired external-Agent token usage for a RepoMind MCP experiment.

The primary comparison only includes tasks passed by both cohorts. This prevents a
lower token count from being reported as a saving when it came from an incomplete
answer. Token counts must be copied from the external Agent's completed-turn usage
record; source characters are reported separately as a context-volume proxy.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


class TokenSavingsReportError(RuntimeError):
    """Raised when a benchmark capture is not comparable or auditable."""


USAGE_SOURCE = "codex_exec_json.turn.completed"
COMPARABLE_FIELDS = (
    "codex_version",
    "model",
    "reasoning_effort",
    "bypass_sandbox",
    "timeout_seconds",
    "mcp_profile",
)
DEFAULT_ACCEPTANCE = {
    "min_benchmark_count": 3,
    "min_task_count": 20,
    "min_both_passed_count": 20,
    "min_independent_repeats": 2,
    "require_treatment_pass_rate_at_least_baseline": True,
}


def _read_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TokenSavingsReportError(f"Cannot read {label} at {path}: {exc}") from exc


def _read_object(path: Path, label: str) -> dict[str, Any]:
    payload = _read_json(path, label)
    if not isinstance(payload, dict):
        raise TokenSavingsReportError(f"{label} at {path} must be a JSON object.")
    return payload


def _resolve(base: Path, raw: object, label: str) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise TokenSavingsReportError(f"{label} must be a non-empty path string.")
    path = Path(raw).expanduser()
    resolved = path.resolve() if path.is_absolute() else (base / path).resolve()
    if not resolved.is_file():
        raise TokenSavingsReportError(f"{label} does not exist: {resolved}")
    return resolved


def _percent_saving(baseline: int, treatment: int) -> float | None:
    if baseline <= 0:
        return None
    return round((baseline - treatment) * 100 / baseline, 2)


def _add_cost_fields(values: dict[str, Any]) -> None:
    for cohort in ("baseline", "treatment"):
        values[f"{cohort}_total_tokens"] = (
            values[f"{cohort}_input_tokens"] + values[f"{cohort}_output_tokens"]
        )
    for metric in ("input_tokens", "output_tokens", "total_tokens"):
        baseline = values[f"baseline_{metric}"]
        treatment = values[f"treatment_{metric}"]
        values[f"{metric}_saved"] = baseline - treatment
        values[f"{metric}_saving_percent"] = _percent_saving(baseline, treatment)


def _load_run(entry: dict[str, Any], base: Path) -> dict[str, Any]:
    benchmark_id = entry.get("benchmark_id")
    if not isinstance(benchmark_id, str) or not benchmark_id.strip():
        raise TokenSavingsReportError("Every batch run needs a non-empty benchmark_id.")
    results_path = _resolve(base, entry.get("results"), f"run {benchmark_id}.results")
    metadata_path = _resolve(base, entry.get("metadata"), f"run {benchmark_id}.metadata")
    rows = _read_json(results_path, f"results for {benchmark_id}")
    metadata = _read_object(metadata_path, f"metadata for {benchmark_id}")
    if not isinstance(rows, list) or not rows:
        raise TokenSavingsReportError(f"Results for {benchmark_id} must be a non-empty JSON array.")
    if metadata.get("benchmark_id") != benchmark_id:
        raise TokenSavingsReportError(f"Metadata benchmark_id does not match batch entry for {benchmark_id}.")
    missing_conditions = [field for field in COMPARABLE_FIELDS if metadata.get(field) in (None, "")]
    if missing_conditions:
        raise TokenSavingsReportError(
            f"Metadata for {benchmark_id} lacks comparable conditions: {', '.join(missing_conditions)}."
        )

    by_task: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise TokenSavingsReportError(f"Results for {benchmark_id} contain a non-object row.")
        task_id, mode = row.get("task_id"), row.get("mode")
        if not isinstance(task_id, str) or not task_id.strip() or mode not in {"baseline", "treatment"}:
            raise TokenSavingsReportError(f"Results for {benchmark_id} contain an invalid task_id or mode.")
        task = by_task.setdefault(task_id, {})
        if mode in task:
            raise TokenSavingsReportError(f"Results for {benchmark_id} contain duplicate {mode}/{task_id} rows.")
        if not isinstance(row.get("passed"), bool):
            raise TokenSavingsReportError(f"Results for {benchmark_id} have invalid passed for {mode}/{task_id}.")
        for field in ("input_tokens", "output_tokens", "source_characters_received"):
            if not isinstance(row.get(field), int) or row[field] < 0:
                raise TokenSavingsReportError(f"Results for {benchmark_id} have invalid {field} for {mode}/{task_id}.")
        has_auditable_usage = row.get("usage_provenance") == USAGE_SOURCE
        if row["passed"] and not has_auditable_usage:
            raise TokenSavingsReportError(
                f"Results for {benchmark_id} need usage_provenance={USAGE_SOURCE!r} for {mode}/{task_id}."
            )
        trace_hash = row.get("raw_trace_sha256")
        if row["passed"] and (not isinstance(trace_hash, str) or len(trace_hash) != 64):
            raise TokenSavingsReportError(f"Results for {benchmark_id} lack a raw_trace_sha256 for {mode}/{task_id}.")
        task[mode] = row
    incomplete = sorted(task_id for task_id, task in by_task.items() if set(task) != {"baseline", "treatment"})
    if incomplete:
        raise TokenSavingsReportError(f"Results for {benchmark_id} lack one cohort for: {', '.join(incomplete)}.")
    failure_classes: dict[str, int] = {}
    failure_classes_by_cohort: dict[str, dict[str, int]] = {"baseline": {}, "treatment": {}}
    statuses: dict[str, int] = {}
    statuses_by_cohort: dict[str, dict[str, int]] = {"baseline": {}, "treatment": {}}
    for task in by_task.values():
        for cohort, row in task.items():
            status = str(row.get("status") or ("completed" if row["passed"] else "failed"))
            statuses[status] = statuses.get(status, 0) + 1
            cohort_statuses = statuses_by_cohort[cohort]
            cohort_statuses[status] = cohort_statuses.get(status, 0) + 1
            if not row["passed"]:
                failure_class = str(row.get("failure_class") or "rubric_failed")
                failure_classes[failure_class] = failure_classes.get(failure_class, 0) + 1
                cohort_failures = failure_classes_by_cohort[cohort]
                cohort_failures[failure_class] = cohort_failures.get(failure_class, 0) + 1
    return {
        "benchmark_id": benchmark_id,
        "run_id": str(entry.get("run_id") or metadata.get("repeat_id") or "repeat-1"),
        "metadata": metadata,
        "tasks": by_task,
        "failure_classes": failure_classes,
        "failure_classes_by_cohort": failure_classes_by_cohort,
        "statuses": statuses,
        "statuses_by_cohort": statuses_by_cohort,
    }


def _acceptance_config(batch: dict[str, Any]) -> dict[str, Any]:
    raw = batch.get("acceptance")
    if raw is None:
        return dict(DEFAULT_ACCEPTANCE)
    if not isinstance(raw, dict):
        raise TokenSavingsReportError("batch config.acceptance must be an object.")
    config = dict(DEFAULT_ACCEPTANCE)
    config.update(raw)
    integer_fields = ("min_benchmark_count", "min_task_count", "min_both_passed_count", "min_independent_repeats")
    for field in integer_fields:
        if not isinstance(config[field], int) or config[field] < 1:
            raise TokenSavingsReportError(f"acceptance.{field} must be a positive integer.")
    if not isinstance(config["require_treatment_pass_rate_at_least_baseline"], bool):
        raise TokenSavingsReportError(
            "acceptance.require_treatment_pass_rate_at_least_baseline must be boolean."
        )
    return config


def _evaluate_acceptance(
    *, batch: dict[str, Any], loaded: list[dict[str, Any]], aggregate: dict[str, Any]
) -> dict[str, Any]:
    config = _acceptance_config(batch)
    repeat_ids = {
        str(run["metadata"].get("repeat_id") or "repeat-1")
        for run in loaded
    }
    repository_ids = {
        str(
            run["metadata"].get("repository_id")
            or run["metadata"].get("repository_path")
            or run["metadata"].get("commit")
        )
        for run in loaded
    }
    gates = {
        "repository_count": {
            "actual": len(repository_ids),
            "minimum": config["min_benchmark_count"],
            "passed": len(repository_ids) >= config["min_benchmark_count"],
        },
        "task_count": {
            "actual": aggregate["task_count"],
            "minimum": config["min_task_count"],
            "passed": aggregate["task_count"] >= config["min_task_count"],
        },
        "both_passed_count": {
            "actual": aggregate["both_passed_count"],
            "minimum": config["min_both_passed_count"],
            "passed": aggregate["both_passed_count"] >= config["min_both_passed_count"],
        },
        "independent_repeats": {
            "actual": len(repeat_ids),
            "minimum": config["min_independent_repeats"],
            "passed": len(repeat_ids) >= config["min_independent_repeats"],
        },
    }
    if config["require_treatment_pass_rate_at_least_baseline"]:
        gates["treatment_pass_rate"] = {
            "actual": aggregate["treatment_pass_rate"],
            "minimum": aggregate["baseline_pass_rate"],
            "passed": aggregate["treatment_pass_rate"] >= aggregate["baseline_pass_rate"],
        }
    failed = [name for name, gate in gates.items() if not gate["passed"]]
    return {
        "status": "accepted" if not failed else "not_accepted",
        "publishable_token_conclusion": not failed,
        "failed_gates": failed,
        "config": config,
        "repeat_ids": sorted(repeat_ids),
        "repository_ids": sorted(repository_ids),
        "gates": gates,
    }


def build_report(batch_path: Path) -> dict[str, Any]:
    batch = _read_object(batch_path, "batch config")
    runs = batch.get("runs")
    if not isinstance(runs, list) or not runs:
        raise TokenSavingsReportError("batch config.runs must be a non-empty array.")
    if any(not isinstance(entry, dict) for entry in runs):
        raise TokenSavingsReportError("Every batch run must be an object.")
    loaded = [_load_run(entry, batch_path.parent) for entry in runs]
    identifiers = [(run["benchmark_id"], run["run_id"]) for run in loaded]
    if len(set(identifiers)) != len(identifiers):
        raise TokenSavingsReportError("batch config contains duplicate benchmark_id/run_id values.")

    mismatches: dict[str, list[str]] = {}
    for field in COMPARABLE_FIELDS:
        values = {str(run["metadata"][field]) for run in loaded}
        if len(values) != 1:
            mismatches[field] = sorted(values)
    if mismatches:
        detail = "; ".join(f"{field}={values}" for field, values in mismatches.items())
        raise TokenSavingsReportError(f"Runs use incompatible conditions: {detail}.")

    totals: dict[str, Any] = {
        "task_count": 0,
        "baseline_passed": 0,
        "treatment_passed": 0,
        "both_passed_count": 0,
        "baseline_only_passed_count": 0,
        "treatment_only_passed_count": 0,
        "both_failed_count": 0,
        "baseline_input_tokens": 0,
        "treatment_input_tokens": 0,
        "baseline_output_tokens": 0,
        "treatment_output_tokens": 0,
        "baseline_source_characters": 0,
        "treatment_source_characters": 0,
    }
    per_run: list[dict[str, Any]] = []
    for run in loaded:
        run_totals = {key: 0 for key in totals}
        for task in run["tasks"].values():
            baseline, treatment = task["baseline"], task["treatment"]
            for values in (totals, run_totals):
                values["task_count"] += 1
                values["baseline_passed"] += int(baseline["passed"])
                values["treatment_passed"] += int(treatment["passed"])
            if baseline["passed"] and treatment["passed"]:
                for values in (totals, run_totals):
                    values["both_passed_count"] += 1
                    for cohort, row in (("baseline", baseline), ("treatment", treatment)):
                        values[f"{cohort}_input_tokens"] += row["input_tokens"]
                        values[f"{cohort}_output_tokens"] += row["output_tokens"]
                        values[f"{cohort}_source_characters"] += row["source_characters_received"]
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
            values["baseline_pass_rate"] = round(values["baseline_passed"] / values["task_count"], 4)
            values["treatment_pass_rate"] = round(values["treatment_passed"] / values["task_count"], 4)
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

    totals["baseline_pass_rate"] = round(totals["baseline_passed"] / totals["task_count"], 4)
    totals["treatment_pass_rate"] = round(totals["treatment_passed"] / totals["task_count"], 4)
    _add_cost_fields(totals)
    totals["source_characters_saved"] = totals["baseline_source_characters"] - totals["treatment_source_characters"]
    totals["source_character_saving_percent"] = _percent_saving(
        totals["baseline_source_characters"], totals["treatment_source_characters"]
    )
    failure_classes: dict[str, int] = {}
    failure_classes_by_cohort: dict[str, dict[str, int]] = {"baseline": {}, "treatment": {}}
    statuses: dict[str, int] = {}
    statuses_by_cohort: dict[str, dict[str, int]] = {"baseline": {}, "treatment": {}}
    for run in loaded:
        for name, count in run["failure_classes"].items():
            failure_classes[name] = failure_classes.get(name, 0) + count
        for cohort, cohort_counts in run["failure_classes_by_cohort"].items():
            for name, count in cohort_counts.items():
                failure_classes_by_cohort[cohort][name] = (
                    failure_classes_by_cohort[cohort].get(name, 0) + count
                )
        for name, count in run["statuses"].items():
            statuses[name] = statuses.get(name, 0) + count
        for cohort, cohort_counts in run["statuses_by_cohort"].items():
            for name, count in cohort_counts.items():
                statuses_by_cohort[cohort][name] = statuses_by_cohort[cohort].get(name, 0) + count
    report = {
        "schema_version": "mcp-token-savings-report-v2",
        "batch_id": batch.get("batch_id") or batch_path.stem,
        "conditions": {field: loaded[0]["metadata"][field] for field in COMPARABLE_FIELDS},
        "usage_provenance": USAGE_SOURCE,
        "comparison_rule": "Token totals include only tasks passed by both cohorts.",
        "source_character_note": "Source characters are a context-volume proxy, not model-billed tokens.",
        "aggregate": totals,
        "cost_comparison": {
            "total_task_count": totals["task_count"],
            "paired_cost_task_count": totals["both_passed_count"],
            "baseline_passed": totals["baseline_passed"],
            "treatment_passed": totals["treatment_passed"],
            "token_totals_include": "Only paired tasks passed by both baseline and treatment.",
            "token_totals_exclude": "Tasks not passed by both cohorts are excluded from token totals.",
            "denominator_description": (
                "Token saving percentages use the baseline token total over paired tasks passed by both "
                "cohorts as the denominator."
            ),
        },
        "runs": per_run,
        "failure_classes": failure_classes,
        "failure_classes_by_cohort": failure_classes_by_cohort,
        "statuses": statuses,
        "statuses_by_cohort": statuses_by_cohort,
    }
    report["acceptance"] = _evaluate_acceptance(batch=batch, loaded=loaded, aggregate=totals)
    return report


def render_markdown(report: dict[str, Any]) -> str:
    aggregate = report["aggregate"]
    return "\n".join(
        [
            f"# MCP Token Savings: {report['batch_id']}",
            "",
            "## Conditions",
            "",
            *(f"- {key}: `{value}`" for key, value in report["conditions"].items()),
            f"- Usage provenance: `{report['usage_provenance']}`",
            "",
            "## Comparable Tasks",
            "",
            f"Both cohorts passed **{aggregate['both_passed_count']}/{aggregate['task_count']}** tasks. "
            f"Baseline pass rate: **{aggregate['baseline_pass_rate']:.2%}**; "
            f"MCP pass rate: **{aggregate['treatment_pass_rate']:.2%}**.",
            f"Token cost comparison denominator: **{report['cost_comparison']['paired_cost_task_count']}** "
            f"paired tasks (of **{report['cost_comparison']['total_task_count']}** total tasks).",
            "",
            "Outcome matrix: "
            f"baseline-only **{aggregate['baseline_only_passed_count']}**; "
            f"MCP-only **{aggregate['treatment_only_passed_count']}**; "
            f"both failed **{aggregate['both_failed_count']}**.",
            "",
            f"Formal acceptance status: **{report['acceptance']['status']}**.",
            *(f"- Failed gate: `{gate}`" for gate in report["acceptance"]["failed_gates"]),
            "",
            "| Metric | Baseline | MCP | Saved | Saving |",
            "| --- | ---: | ---: | ---: | ---: |",
            *(
                f"| {label} | {aggregate[f'baseline_{metric}']:,} | {aggregate[f'treatment_{metric}']:,} | "
                f"{aggregate[f'{metric}_saved']:,} | "
                f"{aggregate[f'{metric}_saving_percent'] if aggregate[f'{metric}_saving_percent'] is not None else 'n/a'}% |"
                for label, metric in (("Input tokens", "input_tokens"), ("Output tokens", "output_tokens"), ("Total tokens", "total_tokens"))
            ),
            "",
            "The source-character comparison is supporting context-volume evidence only: "
            f"{aggregate['source_characters_saved']:,} characters saved "
            f"({aggregate['source_character_saving_percent'] if aggregate['source_character_saving_percent'] is not None else 'n/a'}%).",
            "",
            f"Comparison rule: {report['comparison_rule']}",
            f"Token denominator: {report['cost_comparison']['denominator_description']}",
            "",
            f"Failure classes: `{json.dumps(report['failure_classes'], ensure_ascii=False, sort_keys=True)}`",
            "Failure classes by cohort: "
            f"`{json.dumps(report['failure_classes_by_cohort'], ensure_ascii=False, sort_keys=True)}`",
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", required=True, type=Path, help="JSON file listing result/metadata pairs.")
    parser.add_argument("--output", type=Path, help="Optional JSON report path; otherwise print to stdout.")
    parser.add_argument("--markdown-output", type=Path, help="Optional Markdown report path.")
    args = parser.parse_args()
    try:
        report = build_report(args.batch.resolve())
    except TokenSavingsReportError as exc:
        print(f"MCP token-savings report failed: {exc}")
        return 2
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    if args.markdown_output:
        args.markdown_output.write_text(render_markdown(report), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
