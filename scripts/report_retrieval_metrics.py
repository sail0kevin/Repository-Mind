"""Generate a deterministic retrieval-quality report from captured rankings.

The script intentionally consumes captured rankings instead of opening a live
database. This keeps benchmark results reproducible and prevents accidental
reads of a user's RepoMind data directory.

Example:
    python scripts/report_retrieval_metrics.py benchmark.json --format markdown
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Allow the script to be run directly from the repository root without
# requiring an editable package installation.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from service.evaluation import (
    evaluate_citations,
    evaluate_rankings,
    evaluate_task_completion,
    evaluate_tool_selection,
    summarize_durations,
)


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("queries"), list):
        raise ValueError("input must be an object with a queries array")
    return payload


def _evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    queries = payload["queries"]
    ranked = []
    relevant = []
    for index, query in enumerate(queries, start=1):
        if not isinstance(query, dict):
            raise ValueError(f"query {index} must be an object")
        if not isinstance(query.get("ranked"), list) or not isinstance(query.get("relevant"), list):
            raise ValueError(f"query {index} requires ranked and relevant arrays")
        ranked.append([str(item) for item in query["ranked"]])
        relevant.append([str(item) for item in query["relevant"]])

    metrics = evaluate_rankings(ranked, relevant)
    result = {
        "project": payload.get("project", "RepoMind"),
        "snapshot_commit": payload.get("snapshot_commit"),
        "mode": payload.get("mode", "unknown"),
        **metrics.to_dict(),
    }
    durations = [query.get("duration_ms") for query in queries if isinstance(query, dict) and "duration_ms" in query]
    if durations:
        if len(durations) != len(queries):
            raise ValueError("duration_ms must be provided for every query or none of them")
        result.update(summarize_durations(durations))
    evidence_paths = [query.get("evidence_paths") for query in queries if isinstance(query, dict) and "evidence_paths" in query]
    if evidence_paths:
        if len(evidence_paths) != len(queries):
            raise ValueError("evidence_paths must be provided for every query or none of them")
        result.update(evaluate_citations(evidence_paths, relevant))
    confidences = [query.get("confidence") for query in queries if isinstance(query, dict) and "confidence" in query]
    if confidences:
        if len(confidences) != len(queries):
            raise ValueError("confidence must be provided for every query or none of them")
        if not evidence_paths:
            raise ValueError("task completion requires evidence_paths alongside confidence")
        known_paths = payload.get("known_paths")
        if not isinstance(known_paths, list):
            raise ValueError("task completion requires a top-level known_paths array")
        result.update(
            evaluate_task_completion(
                confidences,
                evidence_paths,
                known_paths,
                relevant_paths=relevant,
            )
        )
    expected_tools = [query.get("expected_tools") for query in queries if isinstance(query, dict) and "expected_tools" in query]
    if expected_tools:
        if len(expected_tools) != len(queries):
            raise ValueError("expected_tools must be provided for every query or none of them")
        route_tools = [query.get("route_tools", []) for query in queries]
        result.update(evaluate_tool_selection(route_tools, expected_tools))
    return result


def _comparison(payload: dict[str, Any], input_path: Path) -> dict[str, dict[str, float]]:
    """从同目录修复前 capture 实时计算可复核对比，禁止硬编码指标。"""
    reference = payload.get("pre_fix_capture")
    if not reference:
        return {}
    pre_path = input_path.parent / str(reference)
    if not pre_path.is_file():
        raise ValueError(f"pre-fix capture does not exist: {pre_path}")
    pre = _evaluate(_load(pre_path))
    post = _evaluate(payload)
    labels = {
        "Recall@5": "recall_at_5",
        "Recall@10": "recall_at_10",
        "MRR": "mrr",
        "Citation hit rate": "citation_hit_rate",
        "Citation precision": "citation_precision",
    }
    return {
        label: {"pre_fix": float(pre[key]), "post_fix": float(post[key])}
        for label, key in labels.items()
        if key in pre and key in post
    }


def _markdown(result: dict[str, Any], payload: dict[str, Any] | None = None) -> str:
    payload = payload or {}
    lines = [
        f"# Retrieval benchmark: {result['project']}",
        "",
        f"- Snapshot: `{result.get('snapshot_commit') or 'not specified'}`",
        f"- Mode: `{result['mode']}`",
        f"- Queries: **{result['query_count']}**",
        f"- Recall@5: **{result['recall_at_5']:.3f}**",
        f"- Recall@10: **{result['recall_at_10']:.3f}**",
        f"- MRR: **{result['mrr']:.3f}**",
    ]
    if "citation_hit_rate" in result:
        lines.extend([
            f"- Citation hit rate: **{result['citation_hit_rate']:.3f}**",
            f"- Citation precision: **{result['citation_precision']:.3f}**",
        ])
    if "duration_p50_ms" in result:
        lines.extend([
            f"- P50 latency: **{result['duration_p50_ms']:.1f} ms**",
            f"- P95 latency: **{result['duration_p95_ms']:.1f} ms**",
        ])
    if "task_completion_rate" in result:
        reasons = result["task_completion_reasons"]
        lines.extend([
            f"- Task completion rate: **{result['task_completion_rate']:.3f}**"
            f" ({reasons['completed']}/{result['task_completion_query_count']})",
            f"  - Citation path missing: {reasons['citation_path_missing']}",
            f"  - Relevant evidence missing: {reasons['relevant_evidence_missing']}",
            f"  - Refused: {reasons['refused']}",
        ])
    if "tool_selection_exact_match_rate" in result:
        lines.extend([
            f"- Tool selection exact-match rate: **{result['tool_selection_exact_match_rate']:.3f}**",
            f"  - Missing expected tool: {result['tool_selection_missing_rate']:.3f}",
            f"  - Unexpected extra tool: {result['tool_selection_extra_rate']:.3f}",
            "  - Scope: expected tools are labeled from the same deterministic Router rules; this is a regression check, not an unseen-query generalization score.",
        ])

    queries = payload.get("queries") if isinstance(payload, dict) else None
    if isinstance(queries, list) and queries:
        lines.extend(["", "## Per-query actual cited files", ""])
        for query in queries:
            actual = list(dict.fromkeys(str(path) for path in query.get("evidence_paths", [])))
            relevant = {str(path) for path in query.get("relevant", [])}
            matched = [path for path in actual if path in relevant]
            failed = not matched
            lines.extend([
                f"### `{query.get('id', 'query')}`",
                "",
                f"- Question: `{query.get('query', '')}`",
                f"- Route tools: `{query.get('route_tools', [])}`",
                f"- Actual cited files: {', '.join(f'`{path}`' for path in actual) or 'none'}",
                f"- Relevant cited files: {', '.join(f'`{path}`' for path in matched) or 'none'}",
                f"- Result: **{'failed' if failed else 'passed'}**"
                + (" — no relevant path was cited." if failed else ""),
                "",
            ])

    comparison = payload.get("comparison") if isinstance(payload, dict) else None
    if isinstance(comparison, dict):
        lines.extend(["## Pre-fix versus post-fix", ""])
        for metric, values in comparison.items():
            if isinstance(values, dict) and "pre_fix" in values and "post_fix" in values:
                lines.append(
                    f"- {metric}: **{float(values['pre_fix']):.3f} → {float(values['post_fix']):.3f}**"
                )
        lines.append("")

    limitations = payload.get("limitations") if isinstance(payload, dict) else None
    if isinstance(limitations, list) and limitations:
        lines.extend(["## Limitations", ""])
        lines.extend(f"- {item}" for item in limitations)
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="captured rankings JSON")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--output", type=Path, help="optional output path")
    args = parser.parse_args()

    payload = _load(args.input)
    result = _evaluate(payload)
    comparison = _comparison(payload, args.input)
    if comparison:
        payload = {**payload, "comparison": comparison}
    rendered = _markdown(result, payload) if args.format == "markdown" else json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="" if rendered.endswith("\n") else "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
