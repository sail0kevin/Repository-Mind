"""Audit frozen complex-context holdout coverage through real RepoMind MCP tools.

This runner measures navigation and context coverage only. It never executes the
indexed target repository and it must run with an immutable, read-only SQLite index.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPTS_DIR.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
for path in (SCRIPTS_DIR, BACKEND_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from context_benchmark import load_tasks, normalized_path
from validate_context_benchmark import validate_manifest


class ToolAuditError(RuntimeError):
    """Raised when a frozen tool-coverage audit cannot be performed safely."""


def _configure_read_only_index(index: dict[str, Any]) -> None:
    data_dir = str(index["data_dir"])
    database_path = str(index["database_path"])
    if not Path(database_path).is_file():
        raise ToolAuditError(f"Frozen index does not exist: {database_path}")
    os.environ["REPOMIND_PATHS__DATA_DIR"] = data_dir
    os.environ["REPOMIND_PATHS__DATABASE_PATH"] = database_path
    os.environ["REPOMIND_SQLITE_READ_ONLY"] = "true"


def _location_evidence(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "path": item.get("path"),
            "symbol": item.get("symbol"),
            "line_start": item.get("start_line"),
            "line_end": item.get("end_line"),
            "role": item.get("role"),
        }
        for item in payload.get("locations", [])
        if isinstance(item, dict)
    ]


def _context_evidence(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "path": item.get("file_path") or item.get("path"),
            "symbol": item.get("symbol"),
            "line_start": item.get("start_line"),
            "line_end": item.get("end_line"),
            "role": item.get("role"),
        }
        for item in payload.get("evidence", [])
        if isinstance(item, dict)
    ]


def _symbol_matches(actual: object, expected: object) -> bool:
    """Compare symbols only when both sides have one.

    Tools differ in whether their evidence carries a symbol field, so the
    headline metric must not penalise a tool merely for omitting it. Callers
    that need symbol accuracy read the separate symbol-precision counters.
    """
    if not isinstance(expected, str) or not expected:
        return True
    if not isinstance(actual, str) or not actual:
        # get_code_context evidence is source-range evidence and does not always
        # include a symbol field. Exact path/range intersection is still auditable.
        return True
    return actual.casefold() == expected.casefold() or actual.casefold().endswith("." + expected.casefold())


def _matches(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    if normalized_path(actual.get("path")) != normalized_path(expected.get("path")):
        return False
    if not _symbol_matches(actual.get("symbol"), expected.get("symbol")):
        return False
    expected_start = expected.get("line_start")
    if expected_start is None:
        return True
    expected_end = expected.get("line_end", expected_start)
    actual_start = actual.get("line_start")
    actual_end = actual.get("line_end", actual_start)
    return (
        isinstance(actual_start, int)
        and isinstance(actual_end, int)
        and actual_end >= expected_start
        and actual_start <= expected_end
    )


def _group_hits(task: dict[str, Any], evidence: list[dict[str, Any]]) -> list[bool]:
    return [
        any(_matches(expected, actual) for expected in alternatives for actual in evidence)
        for alternatives in task["required_evidence_groups"]
    ]


def _result_mode(payload: dict[str, Any]) -> str:
    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("retrieval_mode"), str):
        return data["retrieval_mode"]
    mode = payload.get("retrieval_mode")
    return mode if isinstance(mode, str) else "unknown"


def _call_tool(callable_tool: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        result = callable_tool(**kwargs)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
    return result if isinstance(result, dict) else {"status": "error", "error": "tool returned a non-object result"}


def _tool_summary(rows: list[dict[str, Any]], name: str) -> dict[str, Any]:
    total_groups = sum(len(row["required_evidence_group_hits"]) for row in rows)
    hit_groups = sum(sum(row["required_evidence_group_hits"]) for row in rows)
    task_hits = sum(all(row["required_evidence_group_hits"]) for row in rows)
    path_total = sum(len(row["required_affected_path_hits"]) for row in rows)
    path_hits = sum(sum(row["required_affected_path_hits"]) for row in rows)
    modes = Counter(row["retrieval_mode"] for row in rows)
    statuses = Counter(row["status"] for row in rows)
    roles = Counter(
        role
        for row in rows
        for role in row["evidence_roles"]
        if isinstance(role, str) and role
    )
    symbol_bearing = sum(
        1
        for row in rows
        for item in row["evidence"]
        if isinstance(item.get("symbol"), str) and item.get("symbol")
    )
    evidence_total = sum(len(row["evidence"]) for row in rows)
    return {
        "tool": name,
        "task_count": len(rows),
        "all_required_evidence_groups_hit": task_hits,
        "all_required_evidence_groups_hit_rate": task_hits / len(rows) if rows else 0.0,
        "evidence_group_hits": hit_groups,
        "evidence_group_total": total_groups,
        "evidence_group_coverage": hit_groups / total_groups if total_groups else 0.0,
        "required_affected_path_hits": path_hits,
        "required_affected_path_total": path_total,
        "required_affected_path_coverage": path_hits / path_total if path_total else 0.0,
        "statuses": dict(sorted(statuses.items())),
        "retrieval_modes": dict(sorted(modes.items())),
        "evidence_roles": dict(sorted(roles.items())),
        "symbol_bearing_evidence": symbol_bearing,
        "symbol_bearing_evidence_total": evidence_total,
        "symbol_bearing_rate": symbol_bearing / evidence_total if evidence_total else 0.0,
    }


def audit(manifest_path: Path, limit: int) -> dict[str, Any]:
    manifest = validate_manifest(manifest_path.resolve())
    _configure_read_only_index(manifest)

    # Settings are cached at import time, so MCP imports must occur only after
    # the manifest-bound read-only environment has been injected.
    from service.mcp_server.tools import get_code_context, locate_code

    holdout = load_tasks(Path(manifest["task_file"]), require_all_categories=False)
    tool_rows: dict[str, list[dict[str, Any]]] = {"locate_code": [], "get_code_context": [], "combined": []}

    for task in holdout["tasks"]:
        common = {
            "repo_id": manifest["repo_id"],
            "question": task["question"],
            "snapshot_id": manifest["snapshot_id"],
        }
        locate_result = _call_tool(locate_code, **common, limit=limit, compact=True)
        context_result = _call_tool(get_code_context, **common, limit=limit)
        result_specs = {
            "locate_code": (locate_result, _location_evidence(locate_result)),
            "get_code_context": (context_result, _context_evidence(context_result)),
        }
        combined_evidence = result_specs["locate_code"][1] + result_specs["get_code_context"][1]
        result_specs["combined"] = (
            {"status": "combined", "retrieval_mode": "combined"},
            combined_evidence,
        )
        for tool_name, (payload, evidence) in result_specs.items():
            observed_paths = {normalized_path(item.get("path")) for item in evidence}
            tool_rows[tool_name].append(
                {
                    "task_id": task["id"],
                    "category": task["category"],
                    "status": str(payload.get("status", "unknown")),
                    "retrieval_mode": _result_mode(payload),
                    "returned_evidence_count": len(evidence),
                    "required_evidence_group_hits": _group_hits(task, evidence),
                    "required_affected_path_hits": [
                        normalized_path(path) in observed_paths for path in task["required_affected_paths"]
                    ],
                    "evidence_roles": [item.get("role") for item in evidence],
                    "evidence": evidence,
                }
            )

    return {
        "scope": "tool_level_navigation_and_context_coverage",
        "not_a_measure_of": "coding_agent_final_answer_pass_rate",
        "benchmark_id": manifest["benchmark_id"],
        "repository_commit": manifest["commit"],
        "repo_id": manifest["repo_id"],
        "snapshot_id": manifest["snapshot_id"],
        "task_count": len(holdout["tasks"]),
        "read_only_sqlite": True,
        "tool_summaries": {name: _tool_summary(rows, name) for name, rows in tool_rows.items()},
        "task_results": tool_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=6)
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")
    try:
        result = audit(args.manifest, args.limit)
    except Exception as exc:  # noqa: BLE001
        print(f"Context tool audit failed: {exc}", file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["tool_summaries"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())