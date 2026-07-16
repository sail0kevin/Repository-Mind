"""M1 Snapshot ingest 的幂等、切换和失败隔离测试。"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from service.core.ingest_service import ingest_repository_snapshot
from service.storage.repository_store import create_repo_record, get_repo_record
from service.storage.snapshot_store import get_snapshot
from service.storage.sqlite_db import get_connection


def _git(repo: Path, *args: str) -> str:
    """运行最小 Git 命令并返回输出。"""
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def _commit(repo: Path, message: str) -> str:
    """提交测试仓库当前改动并返回 SHA。"""
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", message],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def git_repository(tmp_path: Path) -> Path:
    """创建带两个可索引文件的真实 Git 仓库。"""
    repo = tmp_path / "snapshot-repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, stdout=subprocess.DEVNULL)
    (repo / "app.py").write_text("def alpha():\n    return 'v1'\n", encoding="utf-8")
    (repo / "README.md").write_text("# Snapshot\n\nfirst version\n", encoding="utf-8")
    _commit(repo, "first")
    return repo


def _register(repo: Path) -> str:
    """直接注册测试仓库，首次 ingest 自己负责扫描和建快照。"""
    return create_repo_record(repo, alias=repo.name, current_commit=_git(repo, "rev-parse", "HEAD"))


def _ids(snapshot_id: str, table: str) -> list[str]:
    """读取某快照产物 ID，验证幂等时没有重复或漂移。"""
    with get_connection() as connection:
        rows = connection.execute(
            f"SELECT id FROM {table} WHERE snapshot_id = ? ORDER BY id", (snapshot_id,)
        ).fetchall()
    return [row["id"] for row in rows]


def test_same_sha_returns_existing_snapshot_without_duplicate_chunks(git_repository: Path) -> None:
    """同 SHA 再次 ingest 必须直接复用成功快照，文件和 chunk ID 都保持不变。"""
    repo_id = _register(git_repository)
    first = ingest_repository_snapshot(repo_id)
    first_files = _ids(first.snapshot_id, "files")
    first_chunks = _ids(first.snapshot_id, "chunks")

    second = ingest_repository_snapshot(repo_id)

    assert second.reused is True
    assert second.snapshot_id == first.snapshot_id
    assert _ids(first.snapshot_id, "files") == first_files
    assert _ids(first.snapshot_id, "chunks") == first_chunks
    with get_connection() as connection:
        total = connection.execute(
            "SELECT COUNT(*) AS total FROM repository_snapshots WHERE repo_id = ?", (repo_id,)
        ).fetchone()["total"]
    assert total == 1


def test_new_sha_builds_new_snapshot_then_switches_active(git_repository: Path) -> None:
    """新 SHA 全量构建新快照，成功前后旧数据保留，完成后才切 active。"""
    repo_id = _register(git_repository)
    first = ingest_repository_snapshot(repo_id)
    old_chunk_ids = _ids(first.snapshot_id, "chunks")

    (git_repository / "app.py").write_text("def alpha():\n    return 'v2'\n", encoding="utf-8")
    new_sha = _commit(git_repository, "second")
    second = ingest_repository_snapshot(repo_id)

    assert second.commit_hash == new_sha
    assert second.snapshot_id != first.snapshot_id
    assert get_repo_record(repo_id)["active_snapshot_id"] == second.snapshot_id
    assert get_snapshot(first.snapshot_id)["status"] == "succeeded"
    assert _ids(first.snapshot_id, "chunks") == old_chunk_ids
    assert _ids(second.snapshot_id, "chunks") != old_chunk_ids


def test_failed_new_snapshot_keeps_previous_active(git_repository: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """新提交构建失败只标记新快照 failed，仓库继续使用旧 active。"""
    repo_id = _register(git_repository)
    first = ingest_repository_snapshot(repo_id)
    (git_repository / "broken.py").write_text("def broken():\n    return 2\n", encoding="utf-8")
    failed_sha = _commit(git_repository, "broken")

    def fail_graph(*_args, **_kwargs):
        raise RuntimeError("图谱投影故障")

    monkeypatch.setattr("service.core.ingest_service.project_symbols_to_code_graph", fail_graph)
    with pytest.raises(RuntimeError, match="图谱投影故障"):
        ingest_repository_snapshot(repo_id)

    repo = get_repo_record(repo_id)
    assert repo["active_snapshot_id"] == first.snapshot_id
    with get_connection() as connection:
        failed = connection.execute(
            "SELECT * FROM repository_snapshots WHERE repo_id = ? AND commit_hash = ?",
            (repo_id, failed_sha),
        ).fetchone()
        bound_files = connection.execute(
            "SELECT COUNT(*) AS total FROM files WHERE snapshot_id = ?", (failed["id"],)
        ).fetchone()["total"]
    assert failed["status"] == "failed"
    assert "图谱投影故障" in failed["error"]
    assert bound_files > 0
