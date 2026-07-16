"""M0 接口契约和任务生命周期的可执行回归测试。"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# 测试数据库必须与用户真实数据隔离，并在导入应用前注入配置。
TEST_DIR = Path(__file__).parent / ".tmp"
TEST_DIR.mkdir(exist_ok=True)
os.environ["REPOMIND_PATHS__DATA_DIR"] = str(TEST_DIR)
os.environ["REPOMIND_PATHS__DATABASE_PATH"] = str(TEST_DIR / "test.sqlite3")

from service.config import settings as settings_module  # noqa: E402
from service.main import create_app  # noqa: E402
from service.storage.job_store import (  # noqa: E402
    create_job_record,
    finish_job_record,
    get_job_record,
    recover_interrupted_jobs,
    start_job_record,
    update_job_progress,
)
from service.storage.sqlite_db import get_connection  # noqa: E402


@pytest.fixture(autouse=True)
def clean_database():
    """每个测试都从空数据库开始。"""
    settings_module._settings = None
    database = TEST_DIR / "test.sqlite3"
    database.unlink(missing_ok=True)
    yield
    database.unlink(missing_ok=True)


def _seed_repo_and_graph() -> str:
    """写入最小仓库和图谱数据，专门验证查询契约。"""
    repo_id = "repo_test"
    with get_connection() as connection:
        snapshot_id = "snap_contract"
        connection.execute(
            "INSERT INTO repos (id, alias, repo_path, status) VALUES (?, ?, ?, ?)",
            (repo_id, "测试仓库", str(TEST_DIR), "indexed"),
        )
        connection.execute(
            "INSERT INTO repository_snapshots (id, repo_id, commit_hash, status) VALUES (?, ?, ?, 'succeeded')",
            (snapshot_id, repo_id, "e" * 40),
        )
        connection.execute(
            "UPDATE repos SET active_snapshot_id = ? WHERE id = ?",
            (snapshot_id, repo_id),
        )
        connection.executemany(
            "INSERT INTO code_nodes (id, repo_id, snapshot_id, name, node_type, file_path, start_line) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                ("func:a", repo_id, snapshot_id, "alpha", "function", "a.py", 1),
                ("func:b", repo_id, snapshot_id, "beta", "function", "b.py", 2),
                ("class:c", repo_id, snapshot_id, "Client", "class", "c.py", 3),
            ],
        )
        connection.execute(
            "INSERT INTO code_edges (id, repo_id, snapshot_id, source_id, target_id, edge_type) VALUES (?, ?, ?, ?, ?, ?)",
            ("edge:1", repo_id, snapshot_id, "func:a", "func:b", "calls"),
        )
    return repo_id


def test_health_exposes_backend_identity():
    """Electron 能通过健康接口识别正确实例。"""
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert {
        "status": body["status"],
        "app_name": body["app_name"],
        "app_version": body["app_version"],
        "api_version": body["api_version"],
        "schema_version": body["schema_version"],
        "supported_schema_version": body["supported_schema_version"],
        "database_schema_version": body["database_schema_version"],
        "backend_contract_version": body["backend_contract_version"],
        "instance_id": body["instance_id"],
    } == {
        "status": "ok",
        "app_name": "RepoMind",
        "app_version": "0.1.0",
        "api_version": "v1",
        "schema_version": "7",
        "supported_schema_version": "7",
        "database_schema_version": "7",
        "backend_contract_version": "1",
        "instance_id": "repomind-desktop-backend",
    }
    assert Path(body["database_path"]).resolve() == TEST_DIR.joinpath("test.sqlite3").resolve()


def test_cors_preflight_allows_vite_renderer():
    """开发版 renderer 的真实 Origin 能完成 CORS 预检和健康请求。"""
    origin = "http://localhost:5173"
    with TestClient(create_app()) as client:
        preflight = client.options(
            "/api/v1/health",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        health = client.get("/api/v1/health", headers={"Origin": origin})
        denied = client.options(
            "/api/v1/health",
            headers={
                "Origin": "https://example.invalid",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == origin
    assert "GET" in preflight.headers["access-control-allow-methods"]
    assert "content-type" in preflight.headers["access-control-allow-headers"].lower()
    assert health.status_code == 200
    assert health.headers["access-control-allow-origin"] == origin
    assert denied.headers.get("access-control-allow-origin") is None


def test_code_graph_get_contract_and_legacy_compatibility():
    """新 GET 契约可用，同时旧 POST search/function 参数继续工作。"""
    repo_id = _seed_repo_and_graph()
    with TestClient(create_app()) as client:
        stats = client.get(f"/api/v1/code-graph/{repo_id}/stats")
        search = client.get(f"/api/v1/code-graph/{repo_id}/search", params={"q": "alp"})
        legacy_search = client.post(f"/api/v1/code-graph/{repo_id}/search", json={"query": "beta"})
        legacy_empty_search = client.post(f"/api/v1/code-graph/{repo_id}/search", json={})
        chain = client.get(
            f"/api/v1/code-graph/{repo_id}/call-chain",
            params={"function": "alpha", "direction": "callees", "depth": 2},
        )
        class_result = client.get(f"/api/v1/code-graph/{repo_id}/class", params={"class_name": "Client"})
        important = client.get(f"/api/v1/code-graph/{repo_id}/important")

    assert all(response.status_code == 200 for response in (
        stats, search, legacy_search, legacy_empty_search, chain, class_result, important,
    ))
    stats_body = stats.json()
    assert stats_body["functions"] == 2
    assert stats_body["snapshot_id"] == "snap_contract"

    # 新 GET 保持 matches；旧 POST 继续提供 matches 和 stats，空字典也仍是合法旧请求。
    assert search.json()["matches"][0]["name"] == "alpha"
    legacy_search_body = legacy_search.json()
    assert legacy_search_body["matches"][0]["name"] == "beta"
    assert legacy_search_body["stats"] == stats_body
    assert legacy_empty_search.json()["matches"] == []
    assert legacy_empty_search.json()["stats"] == stats_body

    # 历史重要节点客户端按 results/functions 读取列表，现代客户端按 nodes 读取。
    important_body = important.json()
    assert important_body["nodes"][0]["importance"] == 1
    assert important_body["results"] == important_body["nodes"]
    assert important_body["functions"] == important_body["nodes"]
    assert important_body["stats"] == stats_body

    # 历史调用链字段 chain 和类字段 relations/stats 均保留，新结构化字段仍可用。
    chain_body = chain.json()
    assert chain_body["symbol"] == "alpha"
    assert chain_body["edges"][0]["target_id"] == "func:b"
    assert chain_body["chain"] == chain_body["edges"]
    assert chain_body["stats"] == stats_body
    class_body = class_result.json()
    assert class_body["class_node"]["name"] == "Client"
    assert class_body["relations"] == []
    assert class_body["stats"] == stats_body


def test_job_lifecycle_progress_and_recovery():
    """任务按 queued→running→终态运行，进度不回退，陈旧 running 会恢复。"""
    job_id = create_job_record("ingest")
    assert get_job_record(job_id)["status"] == "queued"
    assert start_job_record(job_id)
    running = get_job_record(job_id)
    assert running["status"] == "running"
    assert running["started_at"] is not None
    update_job_progress(job_id, 0.8)
    update_job_progress(job_id, 0.3)
    assert get_job_record(job_id)["progress"] == pytest.approx(0.8)
    assert finish_job_record(job_id, "succeeded")
    finished = get_job_record(job_id)
    assert finished["status"] == "succeeded"
    assert finished["progress"] == pytest.approx(1.0)
    assert finished["finished_at"] is not None

    stale_id = create_job_record("workflow_analysis")
    start_job_record(stale_id)
    assert recover_interrupted_jobs() == 1
    assert get_job_record(stale_id)["status"] == "interrupted"
