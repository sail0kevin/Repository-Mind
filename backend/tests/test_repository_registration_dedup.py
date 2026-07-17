"""仓库来源去重测试：同路径和同 GitHub URL 始终复用 repo_id。"""
from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from service.core.workflow_analysis import register_cloned_repository
from service.main import create_app
from service.storage.repository_store import create_repo_record, list_repo_records
from service.storage.snapshot_store import get_active_snapshot


def _git_repo(path: Path) -> Path:
    """创建带 commit 的最小仓库。"""
    path.mkdir()
    subprocess.run(["git", "init", str(path)], check=True, stdout=subprocess.DEVNULL)
    (path / "app.py").write_text("print('ok')\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(path), "-c", "user.name=Test", "-c", "user.email=test@example.com",
         "commit", "-m", "initial"], check=True, stdout=subprocess.DEVNULL,
    )
    return path


def test_local_path_repeated_registration_returns_one_repo(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "same-local")
    with TestClient(create_app()) as client:
        first = client.post("/api/v1/repos", json={"repo_path": str(repo)})
        second = client.post("/api/v1/repos", json={"repo_path": str(repo) + "/."})
    assert first.status_code == second.status_code == 200
    assert first.json()["repo_id"] == second.json()["repo_id"]
    assert len(list_repo_records()) == 1


def test_github_registration_without_auto_ingest_returns_registered_repo(tmp_path: Path, monkeypatch) -> None:
    """桌面端可先取得 repo_id，再自行启动首次 ingest，不要求预先存在 succeeded 快照。"""
    repo = _git_repo(tmp_path / "github-no-ingest")
    monkeypatch.setattr("service.api.v1.repos.clone_public_github_repo", lambda _url: repo)

    with TestClient(create_app()) as client:
        response = client.post("/api/v1/analysis/analyze", json={
            "github_url": "https://github.com/owner/no-ingest",
            "auto_ingest": False,
        })

    assert response.status_code == 200
    body = response.json()
    assert body["response_type"] == "registration"
    assert body["status"] == "registered"
    assert body["repo_id"]
    assert body["current_commit"]
    assert body["file_count"] == 1
    assert "analysis_id" not in body
    assert "snapshot_id" not in body
    assert get_active_snapshot(body["repo_id"]) is None


def test_github_registration_without_auto_ingest_uses_existing_active_snapshot(tmp_path: Path, monkeypatch) -> None:
    """重复登记已有 active 快照的仓库时，关闭自动索引仍返回完整分析报告。"""
    repo = _git_repo(tmp_path / "github-existing-snapshot")
    monkeypatch.setattr("service.api.v1.repos.clone_public_github_repo", lambda _url: repo)

    with TestClient(create_app()) as client:
        first = client.post("/api/v1/analysis/analyze", json={
            "github_url": "https://github.com/owner/existing-snapshot",
            "auto_ingest": True,
        })
        second = client.post("/api/v1/analysis/analyze", json={
            "github_url": "https://github.com/owner/existing-snapshot",
            "auto_ingest": False,
        })

    assert first.status_code == second.status_code == 200
    first_body = first.json()
    second_body = second.json()
    assert second_body["response_type"] == "workflow_report"
    assert second_body["repo"]["repo_id"] == first_body["repo"]["repo_id"]
    assert second_body["snapshot_id"] == first_body["snapshot_id"]
    assert second_body["commit"] == first_body["commit"]


def test_github_registration_with_auto_ingest_returns_snapshot(tmp_path: Path, monkeypatch) -> None:
    """保持旧默认：auto_ingest=true 完成索引并返回 succeeded active 快照。"""
    repo = _git_repo(tmp_path / "github-auto-ingest")
    monkeypatch.setattr("service.api.v1.repos.clone_public_github_repo", lambda _url: repo)

    with TestClient(create_app()) as client:
        response = client.post("/api/v1/analysis/analyze", json={
            "github_url": "https://github.com/owner/auto-ingest",
            "auto_ingest": True,
        })

    assert response.status_code == 200
    body = response.json()
    snapshot = get_active_snapshot(body["repo"]["repo_id"])
    assert snapshot is not None
    assert snapshot["status"] == "succeeded"
    assert body["snapshot_id"] == snapshot["id"]
    assert body["commit"] == snapshot["commit_hash"]


def test_remote_url_variants_reuse_same_repo(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "github-clone")
    first = register_cloned_repository(repo, "https://github.com/Owner/Project.git")
    second = register_cloned_repository(repo, "https://github.com/owner/project/")
    # create_repo_record 也必须服从同一来源规则，而不是绕过去生成重复项。
    third = create_repo_record(tmp_path / "other-path", "other", remote_url="https://github.com/OWNER/PROJECT")
    assert first == second == third
    assert len(list_repo_records()) == 1
