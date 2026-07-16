"""注册后首次索引的 HTTP 回归：create -> ingest -> succeeded -> files。"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

from fastapi.testclient import TestClient

from service.main import create_app


def _git(repo: Path, *args: str) -> None:
    """为真实 HTTP 流程建立最小 Git 仓库。"""
    subprocess.run(["git", "-C", str(repo), *args], check=True, stdout=subprocess.DEVNULL)


def test_http_create_then_ingest_succeeds_before_files_load(tmp_path: Path) -> None:
    """新仓库不预读 files：POST ingest 成功后 GET files 才可读取。"""
    repo = tmp_path / "http-registration-repo"
    repo.mkdir()
    _git(repo, "init")
    (repo / "app.py").write_text("def greeting():\n    return 'hello'\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "initial")

    with TestClient(create_app()) as client:
        created = client.post("/api/v1/repos", json={"repo_path": str(repo), "alias": "HTTP flow"})
        assert created.status_code == 200
        repo_id = created.json()["repo_id"]

        ingest = client.post(f"/api/v1/repos/{repo_id}/ingest")
        assert ingest.status_code == 200
        job_id = ingest.json()["job_id"]
        assert job_id

        for _ in range(100):
            job = client.get(f"/api/v1/jobs/{job_id}")
            assert job.status_code == 200
            status = job.json()["status"]
            if status in {"succeeded", "failed", "cancelled", "interrupted"}:
                break
            time.sleep(0.05)
        assert status == "succeeded", job.json()

        files = client.get(f"/api/v1/repos/{repo_id}/files")
        assert files.status_code == 200
        assert [item["relative_path"] for item in files.json()] == ["app.py"]
