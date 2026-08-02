"""Score production ``locate_code`` results against a pinned location manifest.

Unlike the external Codex A/B runner, this command measures only RepoMind's own
candidate locations.  It is useful for separating retrieval misses from a client
that received the right locations but did not cite all of them.  The target checkout
is never executed or modified; the command reads the manifest-bound SQLite index.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


class LocationRetrievalBenchmarkError(RuntimeError):
    """Raised when a location benchmark cannot be safely scored."""


def _load_preflight_module() -> Any:
    import importlib.util

    path = ROOT / "scripts" / "validate_location_benchmark.py"
    spec = importlib.util.spec_from_file_location("repomind_location_preflight", path)
    if spec is None or spec.loader is None:
        raise LocationRetrievalBenchmarkError("Could not load location benchmark preflight.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_tasks(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LocationRetrievalBenchmarkError(f"Cannot read task file {path}: {exc}") from exc
    tasks = payload.get("tasks") if isinstance(payload, dict) else None
    if not isinstance(tasks, list) or not tasks:
        raise LocationRetrievalBenchmarkError("Task file must contain a non-empty tasks array.")
    return tasks


def _normalize_path(value: object) -> str:
    return str(value or "").replace("\\", "/")


def _score_locations(locations: list[dict[str, Any]], expected: list[dict[str, Any]]) -> dict[str, Any]:
    """Score each annotated line independently; one broad range may cover many lines."""
    checks: list[dict[str, Any]] = []
    reciprocal_ranks: list[float] = []
    for gold in expected:
        path = _normalize_path(gold.get("path"))
        start = gold.get("line_start")
        end = gold.get("line_end")
        if not path or not isinstance(start, int) or not isinstance(end, int):
            raise LocationRetrievalBenchmarkError("Task contains an invalid expected location.")
        matching_index = next(
            (
                index
                for index, location in enumerate(locations, start=1)
                if _normalize_path(location.get("file_path")) == path
                and isinstance(location.get("start_line"), int)
                and isinstance(location.get("end_line"), int)
                and int(location["start_line"]) <= start <= int(location["end_line"])
            ),
            None,
        )
        passed = matching_index is not None
        reciprocal_ranks.append(1.0 / matching_index if matching_index is not None else 0.0)
        checks.append({
            "path": path,
            "gold_start": start,
            "gold_end": end,
            "rank": matching_index,
            "passed": passed,
        })
    return {
        "location_checks": checks,
        "passed": bool(checks) and all(item["passed"] for item in checks),
        "location_hit_count": sum(item["passed"] for item in checks),
        "location_count": len(checks),
        "mean_reciprocal_rank": sum(reciprocal_ranks) / len(reciprocal_ranks),
    }


def _summarize(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    if not tasks:
        raise LocationRetrievalBenchmarkError("Cannot summarize an empty benchmark.")
    task_count = len(tasks)
    location_count = sum(int(item["location_count"]) for item in tasks)
    return {
        "task_count": task_count,
        "passed_task_count": sum(bool(item["passed"]) for item in tasks),
        "task_pass_rate": sum(bool(item["passed"]) for item in tasks) / task_count,
        "gold_location_count": location_count,
        "gold_location_coverage": sum(int(item["location_hit_count"]) for item in tasks) / location_count,
        "mean_gold_location_reciprocal_rank": sum(
            float(item["mean_reciprocal_rank"]) for item in tasks
        ) / task_count,
        "duration_p50_ms": _percentile([float(item["duration_ms"]) for item in tasks], 0.5),
        "duration_p95_ms": _percentile([float(item["duration_ms"]) for item in tasks], 0.95),
    }


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * quantile)))
    return round(ordered[index], 3)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _markdown(capture: dict[str, Any]) -> str:
    summary = capture["summary"]
    lines = [
        "# locate_code retrieval benchmark",
        "",
        f"- Benchmark: `{capture['benchmark_id']}`",
        f"- Target commit: `{capture['snapshot_commit']}`",
        f"- Retrieval mode: `{capture['retrieval_mode']}`",
        f"- Tasks: **{summary['passed_task_count']}/{summary['task_count']}**",
        f"- Gold-location coverage: **{summary['gold_location_coverage']:.3f}**",
        f"- Mean gold-location reciprocal rank: **{summary['mean_gold_location_reciprocal_rank']:.3f}**",
        f"- P50 / P95 latency: **{summary['duration_p50_ms']:.1f} ms / {summary['duration_p95_ms']:.1f} ms**",
        "",
        "## Per-task results",
        "",
        "| Task | Passed | Gold locations | Returned locations |",
        "| --- | --- | --- | --- |",
    ]
    for task in capture["tasks"]:
        lines.append(
            f"| `{task['id']}` | {'yes' if task['passed'] else 'no'} | "
            f"{task['location_hit_count']}/{task['location_count']} | {len(task['locations'])} |"
        )
    lines.extend([
        "",
        "## Scope",
        "",
        "- This measures locations returned by RepoMind itself, not whether an external Coding Agent selected every returned location in its final answer.",
        "- The target repository was not executed, modified, or supplied with dependencies.",
        "",
    ])
    return "\n".join(lines)


def run_benchmark(manifest_path: Path, output_dir: Path, limit: int) -> dict[str, Path]:
    preflight = _load_preflight_module()
    try:
        binding = preflight.validate_manifest(manifest_path.resolve())
    except preflight.BenchmarkValidationError as exc:
        raise LocationRetrievalBenchmarkError(f"Benchmark preflight failed: {exc}") from exc
    if output_dir.exists():
        raise LocationRetrievalBenchmarkError(f"Refusing to reuse output directory: {output_dir}")

    tasks = _read_tasks(Path(binding["task_file"]))
    output_dir.mkdir(parents=True)
    sys.path.insert(0, str(BACKEND))
    from service.config import settings as settings_module
    from service.config.settings import Paths, Settings
    from service.mcp_server.tools import locate_code
    from service.storage.sqlite_db import reset_database_initialization

    settings_module._settings = Settings(paths=Paths(
        data_dir=Path(binding["data_dir"]), database_path=Path(binding["database_path"])
    ))
    reset_database_initialization()
    try:
        results: list[dict[str, Any]] = []
        modes: set[str] = set()
        for task in tasks:
            task_id, question = task.get("id"), task.get("query")
            expected = task.get("expected_locations")
            if not isinstance(task_id, str) or not task_id or not isinstance(question, str) or not question.strip():
                raise LocationRetrievalBenchmarkError("Task is missing id or query.")
            if not isinstance(expected, list) or not expected:
                raise LocationRetrievalBenchmarkError(f"Task {task_id} has no expected locations.")
            started = time.perf_counter()
            response = locate_code(binding["repo_id"], question, binding["snapshot_id"], limit)
            duration_ms = round((time.perf_counter() - started) * 1000, 3)
            if response.get("status") in {"error", "not_found"}:
                raise LocationRetrievalBenchmarkError(f"locate_code failed for {task_id}: {response.get('limitations')}")
            data = response.get("data")
            locations = data.get("locations") if isinstance(data, dict) else None
            if not isinstance(locations, list):
                raise LocationRetrievalBenchmarkError(f"locate_code returned no locations array for {task_id}.")
            mode = str(data.get("retrieval_mode") or "unknown")
            modes.add(mode)
            score = _score_locations(locations, expected)
            results.append({
                "id": task_id,
                "query": question,
                "duration_ms": duration_ms,
                "retrieval_mode": mode,
                "locations": [
                    {
                        "file_path": _normalize_path(item.get("file_path")),
                        "start_line": item.get("start_line"),
                        "end_line": item.get("end_line"),
                    }
                    for item in locations
                ],
                **score,
            })
    finally:
        reset_database_initialization()
        settings_module._settings = None

    if len(modes) != 1:
        raise LocationRetrievalBenchmarkError(f"Benchmark used inconsistent retrieval modes: {sorted(modes)}")
    capture = {
        "benchmark_id": binding["benchmark_id"],
        "snapshot_commit": binding["commit"],
        "retrieval_mode": modes.pop(),
        "source": "production locate_code against manifest-bound isolated index",
        "limit": limit,
        "tasks": results,
        "summary": _summarize(results),
    }
    capture_path = output_dir / "location-retrieval-capture.json"
    report_path = output_dir / "location-retrieval-report.md"
    _write_json(capture_path, capture)
    report_path.write_text(_markdown(capture), encoding="utf-8")
    return {"capture": capture_path, "report": report_path}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=6)
    args = parser.parse_args()
    if not 1 <= args.limit <= 12:
        parser.error("--limit must be between 1 and 12")
    try:
        paths = run_benchmark(args.manifest, args.output_dir, args.limit)
    except LocationRetrievalBenchmarkError as exc:
        print(f"Location retrieval benchmark failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({key: str(value) for key, value in paths.items()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
