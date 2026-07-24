from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
from types import ModuleType

import pytest


ROOT = Path(__file__).parents[2]


def _load_capture_script() -> ModuleType:
    path = ROOT / "scripts" / "capture_demo_evidence.py"
    spec = importlib.util.spec_from_file_location("repomind_capture_demo_evidence", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def test_backend_understanding_gold_has_balanced_categories_and_valid_commit_paths() -> None:
    path = ROOT / "examples" / "benchmarks" / "backend-understanding-gold.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    queries = payload["queries"]

    assert len(queries) == 40
    assert len({item["id"] for item in queries}) == 40
    assert len(payload["snapshot_commit"]) == 40
    assert all(item["query"].strip() for item in queries)
    assert all(item["relevant_paths"] for item in queries)
    assert all(isinstance(item["expected_tools"], list) for item in queries)

    category_counts: dict[str, int] = {}
    for item in queries:
        category = item["category"]
        category_counts[category] = category_counts.get(category, 0) + 1
    assert category_counts == {
        "symbol_navigation": 8,
        "dependency_impact": 8,
        "security_review": 8,
        "repository_navigation": 8,
        "test_runtime": 8,
    }

    tree = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", payload["snapshot_commit"]],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    commit_paths = set(tree.stdout.splitlines())
    labeled_paths = {
        relative_path
        for item in queries
        for relative_path in item["relevant_paths"]
    }
    assert labeled_paths <= commit_paths


def test_backend_understanding_capture_matches_gold_contract() -> None:
    gold = json.loads(
        (ROOT / "examples" / "benchmarks" / "backend-understanding-gold.json").read_text(
            encoding="utf-8"
        )
    )
    capture = json.loads(
        (ROOT / "examples" / "benchmarks" / "backend-understanding-capture-v2.json").read_text(
            encoding="utf-8"
        )
    )

    assert capture["snapshot_commit"] == gold["snapshot_commit"]
    assert capture["query_count"] == len(capture["queries"]) == len(gold["queries"])
    assert [item["id"] for item in capture["queries"]] == [item["id"] for item in gold["queries"]]
    assert all(item["ranked"] for item in capture["queries"])
    assert all(item["evidence_paths"] for item in capture["queries"])
    assert all(item["confidence"] for item in capture["queries"])
    assert all("expected_tools" in item and "route_tools" in item for item in capture["queries"])


def test_backend_understanding_published_metrics_are_recomputed_from_capture() -> None:
    path = ROOT / "scripts" / "report_retrieval_metrics.py"
    spec = importlib.util.spec_from_file_location("repomind_report_retrieval_metrics", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    capture = json.loads(
        (ROOT / "examples" / "benchmarks" / "backend-understanding-capture-v2.json").read_text(
            encoding="utf-8"
        )
    )

    result = module._evaluate(capture)

    assert result["query_count"] == 40
    assert result["recall_at_5"] == pytest.approx(0.2666666667)
    assert result["mrr"] == pytest.approx(0.2450297619)
    assert result["task_completion_rate"] == 0.55
    assert result["task_completion_reasons"]["completed"] == 22


@pytest.mark.parametrize(
    ("raw_path", "expected"),
    [
        ("backend/service/main.py", "backend/service/main.py"),
        (r"backend\service\main.py", "backend/service/main.py"),
    ],
)
def test_generic_capture_normalizes_safe_relative_paths(raw_path: str, expected: str) -> None:
    normalize_relative_path = _load_capture_script()._normalize_relative_path

    assert normalize_relative_path(raw_path) == expected


@pytest.mark.parametrize("raw_path", ["", "../secret.txt", "backend/../secret.txt", "/etc/passwd", "C:/secret.txt"])
def test_generic_capture_rejects_unsafe_relative_paths(raw_path: str) -> None:
    normalize_relative_path = _load_capture_script()._normalize_relative_path

    with pytest.raises(RuntimeError, match="无效的相对路径"):
        normalize_relative_path(raw_path)
