from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sqlite3
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


def _load_location_preflight_script() -> ModuleType:
    path = ROOT / "scripts" / "validate_location_benchmark.py"
    spec = importlib.util.spec_from_file_location("repomind_location_benchmark_preflight", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_location_batch_report_script() -> ModuleType:
    path = ROOT / "scripts" / "report_external_location_batch.py"
    spec = importlib.util.spec_from_file_location("repomind_location_batch_report", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_location_index_script() -> ModuleType:
    path = ROOT / "scripts" / "index_location_benchmark.py"
    spec = importlib.util.spec_from_file_location("repomind_location_benchmark_index", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_location_retrieval_benchmark_script() -> ModuleType:
    path = ROOT / "scripts" / "run_location_retrieval_benchmark.py"
    spec = importlib.util.spec_from_file_location("repomind_location_retrieval_benchmark", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_retrieval_benchmark_script() -> ModuleType:
    path = ROOT / "scripts" / "run_retrieval_benchmark.py"
    spec = importlib.util.spec_from_file_location("repomind_retrieval_benchmark", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_relevance_calibration_script() -> ModuleType:
    path = ROOT / "scripts" / "run_relevance_calibration.py"
    spec = importlib.util.spec_from_file_location("repomind_relevance_calibration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_retrieval_regression_gate_script() -> ModuleType:
    path = ROOT / "scripts" / "verify_retrieval_regression.py"
    spec = importlib.util.spec_from_file_location("repomind_retrieval_regression_gate", path)
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


def test_backend_understanding_negative_fixture_is_reviewed_and_pinned() -> None:
    positive = json.loads((ROOT / "examples" / "benchmarks" / "backend-understanding-gold.json").read_text(encoding="utf-8"))
    negative = json.loads((ROOT / "examples" / "benchmarks" / "backend-understanding-negative-v1.json").read_text(encoding="utf-8"))
    queries = negative["queries"]

    assert negative["snapshot_commit"] == positive["snapshot_commit"]
    assert 10 <= len(queries) <= 20
    assert len({item["id"] for item in queries}) == len(queries)
    assert all(item["query"].strip() for item in queries)
    assert all(item["relevant_paths"] == [] for item in queries)
    assert all(item["review_note"].strip() for item in queries)


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


def test_backend_understanding_manifest_matches_gold_file_hash() -> None:
    manifest = json.loads(
        (ROOT / "examples" / "benchmarks" / "backend-understanding.manifest.example.json").read_text(
            encoding="utf-8"
        )
    )
    gold = ROOT / manifest["gold_file"]

    import hashlib

    assert manifest["target"]["commit"] == json.loads(gold.read_text(encoding="utf-8"))["snapshot_commit"]
    assert manifest["gold_sha256"] == hashlib.sha256(gold.read_bytes()).hexdigest()


def test_backend_understanding_offline_regression_gate_recomputes_frozen_metrics() -> None:
    gate = _load_retrieval_regression_gate_script()

    result = gate.verify()

    assert result["query_count"] == 40
    assert result["recall_at_5"] == pytest.approx(0.26666666666666666)
    assert result["recall_at_10"] == pytest.approx(0.37916666666666665)
    assert result["mrr"] == pytest.approx(0.2450297619047619)
    assert result["citation_hit_rate"] == pytest.approx(0.55)
    assert result["task_completion_rate"] == pytest.approx(0.55)
    assert result["tool_selection_exact_match_rate"] == pytest.approx(1.0)


def test_backend_understanding_offline_regression_gate_rejects_capture_drift(tmp_path: Path) -> None:
    gate = _load_retrieval_regression_gate_script()
    gold_path = ROOT / "examples" / "benchmarks" / "backend-understanding-gold.json"
    manifest_path = ROOT / "examples" / "benchmarks" / "backend-understanding.manifest.example.json"
    capture = json.loads((ROOT / "examples" / "benchmarks" / "backend-understanding-capture-v2.json").read_text(encoding="utf-8"))
    capture["queries"][0]["relevant"] = ["C:/not-a-safe-path.py"]
    capture_path = tmp_path / "capture.json"
    capture_path.write_text(json.dumps(capture), encoding="utf-8")

    with pytest.raises(gate.RegressionGateError, match="drifted"):
        gate.verify(gold_path, capture_path, manifest_path)


def test_retrieval_benchmark_redaction_rejects_secrets_and_absolute_paths(tmp_path: Path) -> None:
    runner = _load_retrieval_benchmark_script()
    with pytest.raises(runner.BenchmarkError, match="local absolute path"):
        runner._assert_redacted({"path": str(tmp_path)}, [str(tmp_path)])
    with pytest.raises(runner.BenchmarkError, match="sensitive key"):
        runner._assert_redacted({"api_key": "not-a-real-key"}, [])


def test_retrieval_benchmark_rejects_unsafe_relative_paths() -> None:
    runner = _load_retrieval_benchmark_script()
    assert runner._safe_relative_path(r"backend\service\main.py") == "backend/service/main.py"
    with pytest.raises(runner.BenchmarkError, match="Unsafe relative path"):
        runner._safe_relative_path("C:/users/secret.txt")


def test_retrieval_benchmark_prepares_backend_import_path(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _load_retrieval_benchmark_script()
    backend_path = str(runner.BACKEND)
    monkeypatch.setattr(runner.sys, "path", [path for path in runner.sys.path if path != backend_path])

    runner._prepare_backend_imports()

    assert runner.sys.path[0] == backend_path


def test_retrieval_benchmark_embedding_configuration_records_batch_size(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _load_retrieval_benchmark_script()
    settings: dict[str, object] = {}

    class Secrets:
        def set(self, key: str, value: str) -> None:
            settings[key] = value

    monkeypatch.setattr(runner, "_prepare_backend_imports", lambda: None)
    runner._prepare_backend_imports()
    import service.storage.secret_store as secret_store
    import service.storage.settings_store as settings_store
    monkeypatch.setattr(secret_store, "get_secret_store", lambda: Secrets())
    monkeypatch.setattr(settings_store, "set_setting", lambda key, value: settings.__setitem__(key, value))
    monkeypatch.setenv("TEST_BENCHMARK_EMBEDDING_KEY", "synthetic")
    args = type("Args", (), {
        "embedding_provider": "openai_compatible",
        "embedding_base_url": "http://127.0.0.1:11434/v1",
        "embedding_model": "all-minilm:latest",
        "embedding_key_env": "TEST_BENCHMARK_EMBEDDING_KEY",
        "embedding_max_input_characters": 128,
        "embedding_batch_size": 4,
    })()

    config = runner._configure_embedding("hybrid", {}, args)

    assert settings["embedding_batch_size"] == 4
    assert config["batch_size"] == 4


def test_retrieval_benchmark_reranker_configuration_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _load_retrieval_benchmark_script()
    settings: dict[str, object] = {}

    runner._prepare_backend_imports()
    import service.storage.settings_store as settings_store

    monkeypatch.setattr(settings_store, "set_setting", lambda key, value: settings.__setitem__(key, value))
    args = type("Args", (), {
        "reranker_provider": "flag_embedding",
        "reranker_model": "BAAI/test-reranker",
        "reranker_use_fp16": False,
        "reranker_candidate_limit": 20,
    })()

    config = runner._configure_reranker("hybrid", args)

    assert config == {
        "provider": "flag_embedding", "model": "BAAI/test-reranker", "use_fp16": False,
        "candidate_limit": 20,
    }
    assert settings["reranker_provider"] == "flag_embedding"
    assert settings["reranker_candidate_limit"] == 20
    with pytest.raises(runner.BenchmarkError, match="requires hybrid"):
        runner._configure_reranker("lexical", args)


def test_retrieval_benchmark_requires_rerank_audit_summary() -> None:
    runner = _load_retrieval_benchmark_script()

    assert runner._rerank_summary({"output_summary": {"rerank": {"applied": True, "candidate_count": 50}}}) == {
        "applied": True, "candidate_count": 50,
    }
    with pytest.raises(runner.BenchmarkError, match="rerank audit"):
        runner._rerank_summary({"output_summary": {}})


def test_relevance_calibration_embedding_configuration_records_matching_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_relevance_calibration_script()
    settings: dict[str, object] = {}

    class Secrets:
        def set(self, key: str, value: str) -> None:
            settings[key] = value

    import service.storage.secret_store as secret_store
    import service.storage.settings_store as settings_store

    monkeypatch.setattr(secret_store, "get_secret_store", lambda: Secrets())
    monkeypatch.setattr(settings_store, "set_setting", lambda key, value: settings.__setitem__(key, value))
    monkeypatch.setenv("TEST_CALIBRATION_EMBEDDING_KEY", "synthetic")
    args = type("Args", (), {
        "embedding_provider": "openai_compatible",
        "embedding_base_url": "http://127.0.0.1:11434/v1",
        "embedding_model": "all-minilm:latest",
        "embedding_key_env": "TEST_CALIBRATION_EMBEDDING_KEY",
        "embedding_max_input_characters": 128,
        "embedding_batch_size": 4,
    })()

    config = runner._configure_embedding("hybrid", args)

    assert settings["embedding_max_input_characters"] == 128
    assert settings["embedding_batch_size"] == 4
    assert config["max_input_characters"] == 128
    assert config["batch_size"] == 4


def test_retrieval_metrics_report_groups_rankings_by_category() -> None:
    report = importlib.util.spec_from_file_location(
        "repomind_report_retrieval_metrics_categories", ROOT / "scripts" / "report_retrieval_metrics.py",
    )
    assert report is not None and report.loader is not None
    module = importlib.util.module_from_spec(report)
    report.loader.exec_module(module)
    payload = {
        "queries": [
            {"category": "symbol_navigation", "ranked": ["a"], "relevant": ["a"]},
            {"category": "test_runtime", "ranked": ["x"], "relevant": ["b"]},
        ]
    }

    categories = module._evaluate_categories(payload)

    assert categories["symbol_navigation"]["recall_at_5"] == 1.0
    assert categories["test_runtime"]["mrr"] == 0.0


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


def _create_pinned_benchmark_fixture(tmp_path: Path) -> tuple[Path, str]:
    repository = tmp_path / "target-repository"
    repository.mkdir()
    (repository / "src").mkdir()
    (repository / "src" / "service.py").write_text("def locate_me():\n    return 1\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=repository, check=True, capture_output=True, text=True)
    subprocess.run(["git", "add", "."], cwd=repository, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-c", "user.name=RepoMind Test", "-c", "user.email=test@example.com", "commit", "-m", "fixture"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repository, check=True, capture_output=True, text=True
    ).stdout.strip()
    data_dir = tmp_path / "isolated-index"
    data_dir.mkdir()
    database = data_dir / "repomind.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE repos (id TEXT PRIMARY KEY, repo_path TEXT)")
        connection.execute(
            "CREATE TABLE repository_snapshots (id TEXT PRIMARY KEY, repo_id TEXT, commit_hash TEXT, status TEXT)"
        )
        connection.execute("INSERT INTO repos VALUES (?, ?)", ("repo_fixture", str(repository)))
        connection.execute(
            "INSERT INTO repository_snapshots VALUES (?, ?, ?, ?)",
            ("snap_fixture", "repo_fixture", commit, "succeeded"),
        )
    tasks = tmp_path / "tasks.json"
    tasks.write_text(
        json.dumps(
            {
                "repository_commit": commit,
                "tasks": [
                    {
                        "id": "locate-service",
                        "query": "Find the definition and its return statement.",
                        "expected_locations": [
                            {"path": "src/service.py", "line_start": 1, "line_end": 1},
                            {"path": "src/service.py", "line_start": 2, "line_end": 2},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest = tmp_path / "benchmark.json"
    manifest.write_text(
        json.dumps(
            {
                "benchmark_id": "fixture",
                "repository": {"path": str(repository), "commit": commit},
                "index": {
                    "repo_id": "repo_fixture",
                    "snapshot_id": "snap_fixture",
                    "data_dir": str(data_dir),
                    "database_path": str(database),
                },
                "task_file": str(tasks),
            }
        ),
        encoding="utf-8",
    )
    return manifest, commit


def test_location_benchmark_preflight_accepts_pinned_isolated_index(tmp_path: Path) -> None:
    preflight = _load_location_preflight_script()
    manifest, commit = _create_pinned_benchmark_fixture(tmp_path)

    result = preflight.validate_manifest(manifest)

    assert result["commit"] == commit
    assert result["repo_id"] == "repo_fixture"
    assert result["task_count"] == 1


def test_location_benchmark_preflight_accepts_equivalent_location_groups(tmp_path: Path) -> None:
    preflight = _load_location_preflight_script()
    manifest, _commit = _create_pinned_benchmark_fixture(tmp_path)
    tasks_path = Path(json.loads(manifest.read_text(encoding="utf-8"))["task_file"])
    tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
    task = tasks["tasks"][0]
    tasks["task_type"] = "single_location_navigation"
    task.pop("expected_locations")
    task["acceptable_location_groups"] = [[
        {"path": "src/service.py", "line_start": 1, "line_end": 1},
        {"path": "src/service.py", "line_start": 2, "line_end": 2},
    ]]
    tasks_path.write_text(json.dumps(tasks), encoding="utf-8")

    result = preflight.validate_manifest(manifest)

    assert result["task_count"] == 1


def test_location_benchmark_preflight_rejects_both_location_contracts(tmp_path: Path) -> None:
    preflight = _load_location_preflight_script()
    manifest, _commit = _create_pinned_benchmark_fixture(tmp_path)
    tasks_path = Path(json.loads(manifest.read_text(encoding="utf-8"))["task_file"])
    tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
    tasks["tasks"][0]["acceptable_location_groups"] = [[
        {"path": "src/service.py", "line_start": 1, "line_end": 1},
    ]]
    tasks_path.write_text(json.dumps(tasks), encoding="utf-8")

    with pytest.raises(preflight.BenchmarkValidationError, match="either expected_locations"):
        preflight.validate_manifest(manifest)


def test_external_token_click_v4_manifest_freezes_equivalent_prompt_locations() -> None:
    artifact_dir = ROOT / "e2e-artifacts" / "external-token-study-20260801"
    manifest = json.loads(
        (artifact_dir / "click-eligible-manifest-v4.json").read_text(encoding="utf-8")
    )
    tasks = json.loads(
        (artifact_dir / manifest["task_file"]).read_text(encoding="utf-8")
    )

    assert manifest["benchmark_id"] == "external-token-click-eligible-v4"
    assert tasks["scoring_policy_version"] == "v4-equivalent-definition-or-implementation"
    prompt_task = next(task for task in tasks["tasks"] if task["id"] == "click-prompt-helper")
    assert "expected_locations" not in prompt_task
    assert prompt_task["acceptable_location_groups"] == [[
        {"path": "src/click/termui.py", "line_start": 138, "line_end": 149},
        {"path": "src/click/termui.py", "line_start": 153, "line_end": 164},
        {"path": "src/click/termui.py", "line_start": 167, "line_end": 285},
    ]]


def test_location_benchmark_preflight_rejects_index_for_other_checkout(tmp_path: Path) -> None:
    preflight = _load_location_preflight_script()
    manifest, _commit = _create_pinned_benchmark_fixture(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    with sqlite3.connect(payload["index"]["database_path"]) as connection:
        connection.execute("UPDATE repos SET repo_path = ? WHERE id = ?", (str(tmp_path / "other"), "repo_fixture"))

    with pytest.raises(preflight.BenchmarkValidationError, match="indexed repo_path does not match"):
        preflight.validate_manifest(manifest)


def test_location_retrieval_benchmark_scores_each_gold_line_and_summarizes_tasks() -> None:
    runner = _load_location_retrieval_benchmark_script()
    locations = [
        {"file_path": "src/example.py", "start_line": 10, "end_line": 30},
        {"file_path": "src/other.py", "start_line": 4, "end_line": 8},
    ]
    score = runner._score_locations(locations, [
        {"path": "src/example.py", "line_start": 12, "line_end": 12},
        {"path": "src/example.py", "line_start": 27, "line_end": 27},
        {"path": "src/other.py", "line_start": 6, "line_end": 6},
    ])

    assert score["passed"] is True
    assert score["location_hit_count"] == 3
    assert [item["rank"] for item in score["location_checks"]] == [1, 1, 2]
    assert score["mean_reciprocal_rank"] == pytest.approx(5 / 6)

    summary = runner._summarize([{
        "passed": score["passed"], "location_hit_count": score["location_hit_count"],
        "location_count": score["location_count"], "mean_reciprocal_rank": score["mean_reciprocal_rank"],
        "duration_ms": 42.0,
    }])
    assert summary["task_pass_rate"] == 1.0
    assert summary["gold_location_coverage"] == 1.0
    assert summary["mean_gold_location_reciprocal_rank"] == pytest.approx(5 / 6)


def test_location_benchmark_retry_only_accepts_one_failed_snapshot_for_the_same_pin(tmp_path: Path) -> None:
    index_script = _load_location_index_script()
    manifest, commit = _create_pinned_benchmark_fixture(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    database = Path(payload["index"]["database_path"])
    repository = Path(payload["repository"]["path"])

    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE repository_snapshots SET status = 'failed'")
    index_script._validate_retry_database(database, repository, commit)

    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE repository_snapshots SET status = 'succeeded'")
    with pytest.raises(index_script.BenchmarkIndexError, match="only failed snapshots"):
        index_script._validate_retry_database(database, repository, commit)


def test_external_location_batch_only_compares_cost_for_both_passed_tasks(tmp_path: Path) -> None:
    report_script = _load_location_batch_report_script()
    results = [
        {"task_id": "both", "mode": "baseline", "passed": True, "input_tokens": 100, "output_tokens": 10, "source_characters_received": 1000},
        {"task_id": "both", "mode": "treatment", "passed": True, "input_tokens": 80, "output_tokens": 11, "source_characters_received": 200},
        {"task_id": "treatment-only", "mode": "baseline", "passed": False, "input_tokens": 500, "output_tokens": 20, "source_characters_received": 5000},
        {"task_id": "treatment-only", "mode": "treatment", "passed": True, "input_tokens": 50, "output_tokens": 21, "source_characters_received": 100},
    ]
    results_path = tmp_path / "results.json"
    metadata_path = tmp_path / "metadata.json"
    batch_path = tmp_path / "batch.json"
    results_path.write_text(json.dumps(results), encoding="utf-8")
    metadata_path.write_text(json.dumps({
        "benchmark_id": "fixture", "codex_version": "0.1", "model": "test",
        "reasoning_effort": "low", "bypass_sandbox": True,
    }), encoding="utf-8")
    batch_path.write_text(json.dumps({"runs": [{
        "benchmark_id": "fixture", "results": str(results_path), "metadata": str(metadata_path),
    }]}), encoding="utf-8")

    report = report_script.build_report(batch_path)

    assert report["aggregate"]["task_count"] == 2
    assert report["aggregate"]["baseline_pass_rate"] == 0.5
    assert report["aggregate"]["treatment_pass_rate"] == 1.0
    assert report["aggregate"]["both_passed_count"] == 1
    assert report["aggregate"]["baseline_input_tokens"] == 100
    assert report["aggregate"]["treatment_input_tokens"] == 80
    assert report["aggregate"]["input_token_change_percent"] == -20.0


def test_external_location_batch_counts_timeout_as_a_failed_task(tmp_path: Path) -> None:
    report_script = _load_location_batch_report_script()
    results_path = tmp_path / "results.json"
    metadata_path = tmp_path / "metadata.json"
    batch_path = tmp_path / "batch.json"
    results_path.write_text(json.dumps([
        {"task_id": "timeout", "mode": "baseline", "status": "timeout", "passed": False,
         "input_tokens": 0, "output_tokens": 0, "source_characters_received": 0},
        {"task_id": "timeout", "mode": "treatment", "status": "completed", "passed": True,
         "input_tokens": 100, "output_tokens": 10, "source_characters_received": 1000},
    ]), encoding="utf-8")
    metadata_path.write_text(json.dumps({
        "benchmark_id": "fixture", "codex_version": "0.1", "model": "test",
        "reasoning_effort": "low", "bypass_sandbox": True,
    }), encoding="utf-8")
    batch_path.write_text(json.dumps({"runs": [{
        "benchmark_id": "fixture", "results": str(results_path), "metadata": str(metadata_path),
    }]}), encoding="utf-8")

    report = report_script.build_report(batch_path)

    assert report["aggregate"]["task_count"] == 1
    assert report["aggregate"]["baseline_pass_rate"] == 0.0
    assert report["aggregate"]["treatment_pass_rate"] == 1.0
    assert report["aggregate"]["both_passed_count"] == 0
    assert report["aggregate"]["input_token_change_percent"] is None


def test_external_location_batch_rejects_mixed_model_conditions(tmp_path: Path) -> None:
    report_script = _load_location_batch_report_script()
    entries = []
    for benchmark_id, model in (("one", "model-a"), ("two", "model-b")):
        results_path = tmp_path / f"{benchmark_id}-results.json"
        metadata_path = tmp_path / f"{benchmark_id}-metadata.json"
        results_path.write_text(json.dumps([
            {"task_id": "task", "mode": "baseline", "passed": True, "input_tokens": 10, "output_tokens": 1, "source_characters_received": 10},
            {"task_id": "task", "mode": "treatment", "passed": True, "input_tokens": 9, "output_tokens": 1, "source_characters_received": 9},
        ]), encoding="utf-8")
        metadata_path.write_text(json.dumps({
            "benchmark_id": benchmark_id, "codex_version": "0.1", "model": model,
            "reasoning_effort": "low", "bypass_sandbox": True,
        }), encoding="utf-8")
        entries.append({"benchmark_id": benchmark_id, "results": str(results_path), "metadata": str(metadata_path)})
    batch_path = tmp_path / "mixed-batch.json"
    batch_path.write_text(json.dumps({"runs": entries}), encoding="utf-8")

    with pytest.raises(report_script.BatchReportError, match="incompatible conditions"):
        report_script.build_report(batch_path)
