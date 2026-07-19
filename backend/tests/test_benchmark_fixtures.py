from __future__ import annotations

import json
from pathlib import Path


def test_cross_file_gold_set_has_stable_snapshot_and_expected_evidence() -> None:
    path = Path(__file__).parents[2] / "examples" / "benchmarks" / "code-understanding-gold.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    queries = payload["queries"]

    assert len(queries) >= 8
    assert len({item["id"] for item in queries}) == len(queries)
    assert len(payload["snapshot_commit"]) == 40
    assert all(item["relevant_paths"] for item in queries)
    assert {item["category"] for item in queries} >= {
        "symbol_navigation",
        "dependency_impact",
        "security_review",
    }


def test_demo_evidence_capture_is_traceable_and_has_limitations() -> None:
    path = Path(__file__).parents[2] / "examples" / "benchmarks" / "demo-evidence-capture.json"
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["source_trace"] == "examples/outputs/repomind-demo-trace.json"
    assert len(payload["queries"]) == 3
    assert payload["limitations"]
    assert all(item["evidence_paths"] and item["relevant"] for item in payload["queries"])


def test_post_fix_demo_capture_comes_from_real_api_and_has_expected_routes() -> None:
    root = Path(__file__).parents[2]
    gold = json.loads((root / "examples" / "benchmarks" / "code-understanding-gold.json").read_text(encoding="utf-8"))
    payload = json.loads((root / "examples" / "benchmarks" / "demo-evidence-capture-post-fix.json").read_text(encoding="utf-8"))

    assert payload["snapshot_commit"] == gold["snapshot_commit"]
    assert payload["source"] == "real FastAPI registration/ingest/ask/trace responses"
    assert payload["mode"] == "lexical-only/no-key-fallback"
    assert payload["query_count"] == len(payload["queries"]) == 3
    assert [item["route_tools"] for item in payload["queries"]] == [
        [], ["security_review"], ["dependency_impact"],
    ]
    assert all("duration_ms" not in item for item in payload["queries"])
    assert all(item["evidence_paths"] and all(item["evidence_paths"]) for item in payload["queries"])
    impact = next(item for item in payload["queries"] if item["id"] == "impact-build-message")
    assert set(impact["evidence_paths"]) >= {
        "repomind_demo/service.py",
        "repomind_demo/app/main.py",
        "tests/test_greeting.py",
    }
