"""仓库来源去重测试：同路径和同 GitHub URL 始终复用 repo_id。"""
from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from service.core.workflow_analysis import register_cloned_repository
from service.main import create_app
from service.storage.repository_store import create_repo_record, list_repo_records


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


def test_remote_url_variants_reuse_same_repo(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "github-clone")
    first = register_cloned_repository(repo, "https://github.com/Owner/Project.git")
    second = register_cloned_repository(repo, "https://github.com/owner/project/")
    # create_repo_record 也必须服从同一来源规则，而不是绕过去生成重复项。
    third = create_repo_record(tmp_path / "other-path", "other", remote_url="https://github.com/OWNER/PROJECT")
    assert first == second == third
    assert len(list_repo_records()) == 1
