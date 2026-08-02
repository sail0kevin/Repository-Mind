"""Verify the committed lexical benchmark capture without live services.

This is intentionally an offline contract gate. It validates that the checked-in
gold set and redacted capture still describe the same pinned benchmark, then
recomputes the frozen metrics. It never opens a RepoMind database, calls an
embedding provider, or indexes a target repository.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from service.evaluation import evaluate_citations, evaluate_rankings, evaluate_task_completion, evaluate_tool_selection


DEFAULT_GOLD = ROOT / "examples" / "benchmarks" / "backend-understanding-gold.json"
DEFAULT_CAPTURE = ROOT / "examples" / "benchmarks" / "backend-understanding-capture-v2.json"
DEFAULT_MANIFEST = ROOT / "examples" / "benchmarks" / "backend-understanding.manifest.example.json"
FROZEN_METRICS = {
    "recall_at_5": 0.26666666666666666,
    "recall_at_10": 0.37916666666666665,
    "mrr": 0.2450297619047619,
    "citation_hit_rate": 0.55,
    "task_completion_rate": 0.55,
    "tool_selection_exact_match_rate": 1.0,
}


class RegressionGateError(RuntimeError):
    """Raised when a committed benchmark fixture no longer matches its contract."""


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RegressionGateError(f"Required benchmark file is missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RegressionGateError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RegressionGateError(f"Benchmark file must contain an object: {path}")
    return payload


def _safe_relative_path(value: Any) -> str:
    path = str(value or "").strip().replace("\\", "/")
    posix = PurePosixPath(path)
    windows = PureWindowsPath(path)
    if not path or posix.is_absolute() or windows.is_absolute() or windows.drive or ".." in posix.parts:
        raise RegressionGateError(f"Unsafe benchmark path: {path!r}")
    return path


def verify(gold_path: Path = DEFAULT_GOLD, capture_path: Path = DEFAULT_CAPTURE, manifest_path: Path = DEFAULT_MANIFEST) -> dict[str, float | int | str]:
    gold = _load(gold_path)
    capture = _load(capture_path)
    manifest = _load(manifest_path)
    gold_queries = gold.get("queries")
    capture_queries = capture.get("queries")
    if not isinstance(gold_queries, list) or not isinstance(capture_queries, list):
        raise RegressionGateError("Gold and capture require queries arrays.")
    if len(gold_queries) != 40 or len(capture_queries) != 40:
        raise RegressionGateError("Frozen backend-understanding benchmark requires exactly 40 queries.")
    commit = gold.get("snapshot_commit")
    if not isinstance(commit, str) or len(commit) != 40:
        raise RegressionGateError("Gold set requires a full pinned snapshot commit.")
    if capture.get("snapshot_commit") != commit or manifest.get("target", {}).get("commit") != commit:
        raise RegressionGateError("Gold, capture, and manifest must use the same pinned commit.")
    if manifest.get("gold_sha256") != hashlib.sha256(gold_path.read_bytes()).hexdigest():
        raise RegressionGateError("Manifest gold_sha256 does not match the committed gold set.")

    gold_by_id = {item.get("id"): item for item in gold_queries if isinstance(item, dict)}
    capture_ids = [item.get("id") for item in capture_queries if isinstance(item, dict)]
    if len(gold_by_id) != len(gold_queries) or capture_ids != [item.get("id") for item in gold_queries]:
        raise RegressionGateError("Capture query IDs must exactly match the gold-set order.")

    ranked: list[list[str]] = []
    relevant: list[list[str]] = []
    cited: list[list[str]] = []
    confidences: list[str] = []
    route_tools: list[list[str]] = []
    expected_tools: list[list[str]] = []
    for query in capture_queries:
        if not isinstance(query, dict):
            raise RegressionGateError("Capture query must be an object.")
        query_id = query["id"]
        gold_query = gold_by_id[query_id]
        if query.get("relevant") != gold_query.get("relevant_paths"):
            raise RegressionGateError(f"Capture relevant paths drifted for {query_id!r}.")
        for key in ("ranked", "evidence_paths", "relevant"):
            if not isinstance(query.get(key), list) or not query[key]:
                raise RegressionGateError(f"Capture query {query_id!r} requires non-empty {key}.")
            for path in query[key]:
                _safe_relative_path(path)
        ranked.append([str(path) for path in query["ranked"]])
        cited.append([str(path) for path in query["evidence_paths"]])
        relevant.append([str(path) for path in query["relevant"]])
        confidences.append(str(query.get("confidence") or ""))
        route_tools.append([str(tool) for tool in query.get("route_tools", [])])
        expected_tools.append([str(tool) for tool in gold_query.get("expected_tools", [])])

    known_paths = capture.get("known_paths")
    if not isinstance(known_paths, list) or not known_paths:
        raise RegressionGateError("Capture requires a non-empty known_paths array.")
    for path in known_paths:
        _safe_relative_path(path)

    retrieval = evaluate_rankings(ranked, relevant).to_dict()
    citation = evaluate_citations(cited, relevant)
    completion = evaluate_task_completion(confidences, cited, known_paths, relevant_paths=relevant)
    tools = evaluate_tool_selection(route_tools, expected_tools)
    result: dict[str, float | int | str] = {
        "snapshot_commit": commit,
        **retrieval,
        **citation,
        **completion,
        **tools,
    }
    for key, expected in FROZEN_METRICS.items():
        actual = float(result[key])
        if abs(actual - expected) > 1e-12:
            raise RegressionGateError(f"Frozen {key} changed: expected {expected}, got {actual}.")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--capture", type=Path, default=DEFAULT_CAPTURE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    try:
        result = verify(args.gold, args.capture, args.manifest)
    except RegressionGateError as exc:
        print(f"Retrieval regression gate failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
