"""P2-2 MCP retrieval telemetry persistence, aggregation, and failure isolation."""
from __future__ import annotations

import sqlite3
from types import SimpleNamespace

from fastapi.testclient import TestClient

from service.api.v1.metrics import metrics
from service.config import settings as settings_module
from service.config.settings import Paths, Settings
from service.main import create_app
from service.mcp_server import tools as mcp_tools
from service.mcp_server.tools import locate_code, search_code
from service.storage.repository_store import create_repo_record
from service.storage.retrieval_metrics_store import get_retrieval_metrics, record_retrieval_metric
from service.storage.snapshot_store import get_or_create_snapshot, publish_snapshot
from service.storage.sqlite_db import get_connection
from service.storage.migrations.runner import run_migrations


def _seed_snapshot(tmp_path, alias: str = "metrics") -> tuple[str, str]:
    repo_path = tmp_path / alias
    repo_path.mkdir()
    repo_id = create_repo_record(repo_path, alias, current_commit="a" * 40)
    snapshot, _ = get_or_create_snapshot(repo_id, "a" * 40, "main")
    publish_snapshot(repo_id, snapshot["id"], "main", 0)
    return repo_id, str(snapshot["id"])


def test_v009_is_registered_after_metrics_table_creation(temporary_database) -> None:
    with get_connection() as connection:
        migration = connection.execute("SELECT name FROM schema_migrations WHERE version = 9").fetchone()
        indexes = {
            row[1] for row in connection.execute("PRAGMA index_list(retrieval_metrics)").fetchall()
        }

    assert migration[0] == "redact_retrieval_metric_queries"
    assert {"idx_retrieval_metrics_repo_created", "idx_retrieval_metrics_snapshot_created"} <= indexes


def test_metrics_store_redacts_query_aggregates_and_isolates_repositories(tmp_path) -> None:
    repo_id, snapshot_id = _seed_snapshot(tmp_path, "one")
    other_repo_id, other_snapshot_id = _seed_snapshot(tmp_path, "two")
    record_retrieval_metric(
        repo_id=repo_id,
        snapshot_id=snapshot_id,
        tool_name="search_code",
        retrieval_mode="hybrid",
        query="token=super-secret-value",
        returned_count=3,
        top_score=0.8,
        duration_ms=12.5,
    )
    record_retrieval_metric(
        repo_id=repo_id,
        snapshot_id=snapshot_id,
        tool_name="locate_code",
        retrieval_mode="lexical",
        query="missing",
        returned_count=0,
        top_score=None,
        duration_ms=4,
    )
    record_retrieval_metric(
        repo_id=other_repo_id,
        snapshot_id=other_snapshot_id,
        tool_name="search_code",
        retrieval_mode="hybrid",
        query="other",
        returned_count=1,
        top_score=0.9,
        duration_ms=1,
    )

    with get_connection() as connection:
        query = connection.execute(
            "SELECT query FROM retrieval_metrics WHERE repo_id = ? ORDER BY rowid LIMIT 1", (repo_id,)
        ).fetchone()[0]
    result = get_retrieval_metrics(days=99, repo_id=repo_id)

    assert query == "[redacted]"
    assert result["days"] == 30
    assert result["totals"] == {
        "request_count": 2,
        "average_top_score": 0.8,
        "maximum_top_score": 0.8,
        "average_duration_ms": 8.25,
        "p50_duration_ms": 4.0,
        "p95_duration_ms": 12.5,
    }
    assert result["trend"][0] == {
        "date": result["trend"][0]["date"],
        "request_count": 2,
        "average_top_score": 0.8,
        "maximum_top_score": 0.8,
        "low_score_count": 1,
        "average_duration_ms": 8.25,
        "p50_duration_ms": 4.0,
        "p95_duration_ms": 12.5,
    }
    assert result["breakdown"] == [
        {
            "tool_name": "locate_code",
            "retrieval_mode": "lexical",
            "request_count": 1,
            "low_score_count": 1,
            "average_duration_ms": 4.0,
            "p50_duration_ms": 4.0,
            "p95_duration_ms": 4.0,
        },
        {
            "tool_name": "search_code",
            "retrieval_mode": "hybrid",
            "request_count": 1,
            "low_score_count": 0,
            "average_duration_ms": 12.5,
            "p50_duration_ms": 12.5,
            "p95_duration_ms": 12.5,
        },
    ]


def test_v009_redacts_existing_metric_query_rows(tmp_path) -> None:
    database_path = tmp_path / "metrics-v009.sqlite3"
    connection = sqlite3.connect(database_path)
    try:
        run_migrations(connection, database_path)
        connection.execute("INSERT INTO repos (id, alias, repo_path, status) VALUES ('repo_1', 'repo', 'Z:/repo', 'registered')")
        connection.execute(
            "INSERT INTO repository_snapshots (id, repo_id, commit_hash, status) VALUES ('snapshot_1', 'repo_1', 'a', 'succeeded')"
        )
        connection.execute(
            "INSERT INTO retrieval_metrics (id, repo_id, snapshot_id, tool_name, retrieval_mode, query, returned_count, duration_ms) VALUES ('metric_1', 'repo_1', 'snapshot_1', 'search_code', 'lexical', 'old secret query', 0, 1)"
        )
        connection.execute("DELETE FROM schema_migrations WHERE version = 9")
        connection.commit()

        run_migrations(connection, database_path)

        assert connection.execute("SELECT query FROM retrieval_metrics WHERE id = 'metric_1'").fetchone()[0] == "[redacted]"
    finally:
        connection.close()


def test_metrics_api_obeys_desktop_token_and_returns_trend(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(settings_module, "_settings", Settings(
        api_token="metrics-token",
        paths=Paths(data_dir=data_dir, database_path=data_dir / "repomind.sqlite3"),
    ))
    repo_id, snapshot_id = _seed_snapshot(tmp_path)
    record_retrieval_metric(
        repo_id=repo_id, snapshot_id=snapshot_id, tool_name="search_code",
        retrieval_mode="lexical", query="auth", returned_count=1, top_score=0.2, duration_ms=3,
    )

    with TestClient(create_app()) as client:
        assert client.get("/api/v1/metrics").status_code == 404
        response = client.get(
            "/api/v1/metrics", headers={"X-RepoMind-API-Token": "metrics-token"}
        )

    assert response.status_code == 200
    assert response.json()["totals"]["request_count"] == 1


def test_search_code_records_one_metric_and_telemetry_failure_is_nonfatal(
    tmp_path, monkeypatch
) -> None:
    repo_id, snapshot_id = _seed_snapshot(tmp_path)
    captured: list[dict] = []

    class FakeRetriever:
        def retrieve(self, *_args):
            return SimpleNamespace(
                items=[],
                run=SimpleNamespace(
                    mode="hybrid",
                    channels={"semantic": 1},
                    relevance=SimpleNamespace(observation=SimpleNamespace(rrf_top_score=0.42)),
                ),
            )

    monkeypatch.setattr(mcp_tools, "HybridRetriever", FakeRetriever)
    monkeypatch.setattr(mcp_tools, "record_retrieval_metric", lambda **kwargs: captured.append(kwargs))
    result = search_code(repo_id, "auth", snapshot_id=snapshot_id)

    assert result["status"] == "not_found"
    assert captured[0]["tool_name"] == "search_code"
    assert captured[0]["returned_count"] == 0
    assert captured[0]["top_score"] == 0.42

    def failing_metric(**_kwargs):
        raise RuntimeError("disk unavailable")

    monkeypatch.setattr(mcp_tools, "record_retrieval_metric", failing_metric)
    assert search_code(repo_id, "auth", snapshot_id=snapshot_id)["status"] == "not_found"


def test_locate_code_records_one_metric_for_multiple_internal_retrievals(tmp_path, monkeypatch) -> None:
    repo_id, snapshot_id = _seed_snapshot(tmp_path)
    captured: list[dict] = []

    class FakeRetriever:
        def retrieve(self, _repo_id, _snapshot_id, query, _limit):
            score = 0.8 if query == "Locate auth token" else 0.3
            return SimpleNamespace(
                items=[],
                run=SimpleNamespace(
                    mode="hybrid",
                    channels={"semantic": 1},
                    relevance=SimpleNamespace(observation=SimpleNamespace(rrf_top_score=score)),
                ),
            )

    monkeypatch.setattr(mcp_tools, "HybridRetriever", FakeRetriever)
    monkeypatch.setattr(mcp_tools, "record_retrieval_metric", lambda **kwargs: captured.append(kwargs))

    result = locate_code(repo_id, "Locate auth token", snapshot_id=snapshot_id)

    assert result["status"] == "not_found"
    assert len(captured) == 1
    assert captured[0]["tool_name"] == "locate_code"
    assert captured[0]["top_score"] == 0.8


def test_low_score_alert_only_fires_at_the_start_of_a_streak(tmp_path, caplog) -> None:
    repo_id, snapshot_id = _seed_snapshot(tmp_path)
    for index in range(11):
        record_retrieval_metric(
            repo_id=repo_id,
            snapshot_id=snapshot_id,
            tool_name="search_code",
            retrieval_mode="lexical",
            query=str(index),
            returned_count=0,
            top_score=None,
            duration_ms=1,
        )

    warnings = [record for record in caplog.records if "retrieval quality alert" in record.message]
    assert len(warnings) == 1
