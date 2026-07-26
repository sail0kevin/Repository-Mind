"""Aggregate isolated RepoMind external code-location A/B benchmark runs.

The report intentionally separates all-task pass rates from token/context comparisons.
Token and source-text deltas are calculated only for tasks completed by both cohorts,
so a lower cost never hides a failed location task.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


class BatchReportError(RuntimeError):
    """Raised when benchmark outputs cannot support a comparable aggregate."""


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BatchReportError(f"Cannot read {label} at {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise BatchReportError(f"{label} at {path} must be a JSON object.")
    return payload


def _resolve(base: Path, raw: object, label: str) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise BatchReportError(f"{label} must be a non-empty path string.")
    path = Path(raw).expanduser()
    resolved = path.resolve() if path.is_absolute() else (base / path).resolve()
    if not resolved.is_file():
        raise BatchReportError(f"{label} does not exist: {resolved}")
    return resolved


def _percent_change(baseline: int, treatment: int) -> float | None:
    if baseline <= 0:
        return None
    return round((treatment - baseline) * 100 / baseline, 2)


def _load_run(entry: dict[str, Any], base: Path) -> dict[str, Any]:
    benchmark_id = entry.get("benchmark_id")
    if not isinstance(benchmark_id, str) or not benchmark_id.strip():
        raise BatchReportError("Every batch run needs a non-empty benchmark_id.")
    results_path = _resolve(base, entry.get("results"), f"run {benchmark_id}.results")
    metadata_path = _resolve(base, entry.get("metadata"), f"run {benchmark_id}.metadata")
    rows = json.loads(results_path.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not rows:
        raise BatchReportError(f"Results for {benchmark_id} must be a non-empty JSON array.")
    metadata = _read_object(metadata_path, f"metadata for {benchmark_id}")
    if metadata.get("benchmark_id") != benchmark_id:
        raise BatchReportError(f"Metadata benchmark_id does not match batch entry for {benchmark_id}.")

    by_task: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise BatchReportError(f"Results for {benchmark_id} contain a non-object row.")
        task_id, mode = row.get("task_id"), row.get("mode")
        if not isinstance(task_id, str) or not task_id or mode not in {"baseline", "treatment"}:
            raise BatchReportError(f"Results for {benchmark_id} contain an invalid task_id or mode.")
        task = by_task.setdefault(task_id, {})
        if mode in task:
            raise BatchReportError(f"Results for {benchmark_id} contain duplicate {mode}/{task_id} rows.")
        for field in ("input_tokens", "output_tokens", "source_characters_received"):
            if not isinstance(row.get(field), int) or row[field] < 0:
                raise BatchReportError(f"Results for {benchmark_id} have invalid {field} for {mode}/{task_id}.")
        if not isinstance(row.get("passed"), bool):
            raise BatchReportError(f"Results for {benchmark_id} have invalid passed value for {mode}/{task_id}.")
        task[mode] = row
    incomplete = sorted(task_id for task_id, task in by_task.items() if set(task) != {"baseline", "treatment"})
    if incomplete:
        raise BatchReportError(f"Results for {benchmark_id} lack one cohort for: {', '.join(incomplete)}.")
    return {"benchmark_id": benchmark_id, "metadata": metadata, "tasks": by_task}


def build_report(batch_path: Path) -> dict[str, Any]:
    batch = _read_object(batch_path, "batch config")
    runs = batch.get("runs")
    if not isinstance(runs, list) or not runs:
        raise BatchReportError("batch config.runs must be a non-empty array.")
    loaded = [_load_run(entry, batch_path.parent) for entry in runs if isinstance(entry, dict)]
    if len(loaded) != len(runs):
        raise BatchReportError("Every batch run must be an object.")
    identifiers = [run["benchmark_id"] for run in loaded]
    if len(set(identifiers)) != len(identifiers):
        raise BatchReportError("batch config contains duplicate benchmark_id values.")

    comparable_fields = ("codex_version", "model", "reasoning_effort", "bypass_sandbox")
    reference = loaded[0]["metadata"]
    mismatches: dict[str, list[str]] = {}
    for field in comparable_fields:
        values = {str(run["metadata"].get(field)) for run in loaded}
        if len(values) != 1:
            mismatches[field] = sorted(values)
    if mismatches:
        detail = "; ".join(f"{field}={values}" for field, values in mismatches.items())
        raise BatchReportError(f"Runs use incompatible conditions: {detail}.")

    totals = {
        "task_count": 0,
        "baseline_passed": 0,
        "treatment_passed": 0,
        "both_passed_count": 0,
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
            totals["task_count"] += 1
            run_totals["task_count"] += 1
            for prefix, row in (("baseline", baseline), ("treatment", treatment)):
                if row["passed"]:
                    totals[f"{prefix}_passed"] += 1
                    run_totals[f"{prefix}_passed"] += 1
            if baseline["passed"] and treatment["passed"]:
                totals["both_passed_count"] += 1
                run_totals["both_passed_count"] += 1
                for prefix, row in (("baseline", baseline), ("treatment", treatment)):
                    totals[f"{prefix}_input_tokens"] += row["input_tokens"]
                    totals[f"{prefix}_output_tokens"] += row["output_tokens"]
                    totals[f"{prefix}_source_characters"] += row["source_characters_received"]
                    run_totals[f"{prefix}_input_tokens"] += row["input_tokens"]
                    run_totals[f"{prefix}_output_tokens"] += row["output_tokens"]
                    run_totals[f"{prefix}_source_characters"] += row["source_characters_received"]
        per_run.append({"benchmark_id": run["benchmark_id"], **run_totals})

    for values in (totals, *per_run):
        values["baseline_pass_rate"] = round(values["baseline_passed"] / values["task_count"], 4)
        values["treatment_pass_rate"] = round(values["treatment_passed"] / values["task_count"], 4)
        values["input_token_change_percent"] = _percent_change(
            values["baseline_input_tokens"], values["treatment_input_tokens"]
        )
        values["source_character_change_percent"] = _percent_change(
            values["baseline_source_characters"], values["treatment_source_characters"]
        )
    return {
        "batch_id": batch.get("batch_id") or batch_path.stem,
        "conditions": {field: reference.get(field) for field in comparable_fields},
        "comparison_rule": "Token and source-text totals include only tasks passed by both cohorts.",
        "aggregate": totals,
        "runs": per_run,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", required=True, type=Path, help="JSON file listing result/metadata pairs.")
    parser.add_argument("--output", type=Path, help="Optional JSON report path; otherwise print to stdout.")
    args = parser.parse_args()
    try:
        report = build_report(args.batch.resolve())
    except BatchReportError as exc:
        print(f"Batch report failed: {exc}")
        return 2
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
