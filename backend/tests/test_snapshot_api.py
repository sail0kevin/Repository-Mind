"""M1 Snapshot API 的可执行契约测试。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from service.main import create_app
from service.storage.sqlite_db import get_connection
from service.storage.snapshot_store import create_or_get_snapshot, finish_snapshot, set_active_snapshot


def _seed_repo() -> tuple[str, str]:
    """写入一个带 active 快照的最小仓库。"""
    repo_id = "repo_snapshot_api"
    commit = "a" * 40
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO repos (id, alias, repo_path, branch, commit_hash, status, file_count)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (repo_id, "快照仓库", "/tmp/repo", "main", commit, "registered", 3),
        )
    snapshot = create_or_get_snapshot(repo_id, commit, "main")
    assert finish_snapshot(snapshot["id"], "succeeded")
    assert set_active_snapshot(repo_id, snapshot["id"])
    return repo_id, snapshot["id"]


def test_repo_list_snapshot_list_and_detail_contract():
    """仓库列表、快照列表和详情返回一致的 active 快照字段。"""
    repo_id, snapshot_id = _seed_repo()
    with TestClient(create_app()) as client:
        repos = client.get("/api/v1/repos")
        snapshots = client.get(f"/api/v1/repos/{repo_id}/snapshots")
        detail = client.get(f"/api/v1/repos/{repo_id}/snapshots/{snapshot_id}")

    assert repos.status_code == snapshots.status_code == detail.status_code == 200
    repo = repos.json()[0]
    assert repo["repo_id"] == repo_id
    assert repo["snapshot_id"] == snapshot_id
    assert repo["commit"] == "a" * 40
    assert snapshots.json()["active_snapshot_id"] == snapshot_id
    assert snapshots.json()["snapshots"][0]["is_active"] is True
    assert detail.json()["snapshot_id"] == snapshot_id


def test_old_clients_default_to_active_snapshot_and_new_clients_can_select_it(monkeypatch):
    """不传 snapshot_id 的旧请求仍使用 active，新请求显式传入时返回相同上下文。"""
    repo_id, snapshot_id = _seed_repo()
    from service.core.agent.models import MainAgentResult
    monkeypatch.setattr("service.api.v1.repos.run_main_agent", lambda _context: MainAgentResult(
        answer="ok", evidence=[], confidence="low", used_context=0,
        trace_id="trace", next_steps=[], token_count=0, generation_mode="rule_fallback",
    ))
    monkeypatch.setattr("service.api.v1.repos.create_session_record", lambda *_args: "session")
    monkeypatch.setattr("service.api.v1.repos.bind_trace_session", lambda *_args: None)

    with TestClient(create_app()) as client:
        repo_map = client.get(f"/api/v1/repos/{repo_id}/map")
        summary = client.get(f"/api/v1/repos/{repo_id}/summary")
        old_search = client.post(f"/api/v1/repos/{repo_id}/search", json={"query": "x"})
        new_ask = client.post(
            f"/api/v1/repos/{repo_id}/ask",
            json={"question": "x", "snapshot_id": snapshot_id},
        )

    for response in (repo_map, summary, old_search, new_ask):
        assert response.status_code == 200
        assert response.json()["snapshot_id"] == snapshot_id
        assert response.json()["commit"] == "a" * 40


def test_snapshot_detail_rejects_cross_repo_access():
    """快照详情不能通过另一个仓库 ID 越权读取。"""
    _repo_id, snapshot_id = _seed_repo()
    with get_connection() as connection:
        connection.execute(
            "INSERT INTO repos (id, alias, repo_path, status) VALUES (?, ?, ?, ?)",
            ("repo_other", "其他仓库", "/tmp/other", "registered"),
        )
    with TestClient(create_app()) as client:
        response = client.get(f"/api/v1/repos/repo_other/snapshots/{snapshot_id}")
    assert response.status_code == 404
