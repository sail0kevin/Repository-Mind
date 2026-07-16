"""M1 最终加固：迁移、并发、dirty、图谱隔离和会话绑定测试。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import subprocess
import threading

import pytest

from service.core.ingest_service import ingest_repository_snapshot
from service.core.repo_scanner import RepositoryScanError
from service.storage.migrations.runner import run_migrations
from service.storage.repository_store import create_repo_record
from service.storage.session_store import create_session_record
from service.storage.snapshot_store import recover_building_snapshots
from service.storage.sqlite_db import get_connection


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, stdout=subprocess.DEVNULL)
    (repo / "app.py").write_text("def value():\n    return 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=t@example.com", "commit", "-m", "first"], check=True, stdout=subprocess.DEVNULL)
    return repo


def test_v003_binds_all_reliable_legacy_data_once(tmp_path: Path) -> None:
    db = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(db)
    connection.executescript("""
        CREATE TABLE repos (id TEXT PRIMARY KEY, alias TEXT NOT NULL, repo_path TEXT NOT NULL, branch TEXT, commit_hash TEXT, status TEXT NOT NULL);
        CREATE TABLE files (id TEXT PRIMARY KEY, repo_id TEXT NOT NULL, relative_path TEXT NOT NULL);
        INSERT INTO repos VALUES ('repo_old','old','G:/old','main','abc123','indexed');
        INSERT INTO files VALUES ('file_old','repo_old','README.md');
    """)
    connection.commit()
    run_migrations(connection, db)
    first = connection.execute("SELECT id FROM repository_snapshots WHERE repo_id='repo_old'").fetchall()
    assert len(first) == 1
    snapshot_id = first[0][0]
    assert connection.execute("SELECT active_snapshot_id FROM repos").fetchone()[0] == snapshot_id
    assert connection.execute("SELECT snapshot_id FROM files").fetchone()[0] == snapshot_id
    assert connection.execute("SELECT snapshot_id FROM sessions").fetchall() == []
    run_migrations(connection, db)
    assert connection.execute("SELECT COUNT(*) FROM repository_snapshots").fetchone()[0] == 1
    connection.close()


def test_dirty_worktree_is_rejected(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    repo_id = create_repo_record(repo, repo.name, current_commit=_git(repo, "rev-parse", "HEAD"))
    (repo / "app.py").write_text("dirty", encoding="utf-8")
    with pytest.raises(RepositoryScanError, match="未提交"):
        ingest_repository_snapshot(repo_id)


def test_same_sha_concurrent_calls_build_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    repo_id = create_repo_record(repo, repo.name, current_commit=_git(repo, "rev-parse", "HEAD"))
    barrier = threading.Barrier(2)
    original = __import__("service.core.ingest_service", fromlist=["scan_repository_files"]).scan_repository_files

    def synchronized_scan(path):
        try:
            barrier.wait(timeout=0.2)
        except threading.BrokenBarrierError:
            pass
        return original(path)

    monkeypatch.setattr("service.core.ingest_service.scan_repository_files", synchronized_scan)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: ingest_repository_snapshot(repo_id), range(2)))
    assert results[0].snapshot_id == results[1].snapshot_id
    assert sorted(item.reused for item in results) == [False, True]
    with get_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM repository_snapshots WHERE repo_id=?", (repo_id,)).fetchone()[0] == 1


def test_recovery_never_activates_building_snapshot(tmp_path: Path) -> None:
    with get_connection() as connection:
        connection.execute("INSERT INTO repos (id,alias,repo_path,status) VALUES ('r','r','x','registered')")
        connection.execute("INSERT INTO repository_snapshots (id,repo_id,commit_hash,status) VALUES ('s','r','abc','building')")
    assert recover_building_snapshots() == 1
    with get_connection() as connection:
        assert connection.execute("SELECT status FROM repository_snapshots WHERE id='s'").fetchone()[0] == "failed"
        assert connection.execute("SELECT active_snapshot_id FROM repos WHERE id='r'").fetchone()[0] is None


def test_new_session_binds_current_snapshot(tmp_path: Path) -> None:
    with get_connection() as connection:
        connection.execute("INSERT INTO repos (id,alias,repo_path,status) VALUES ('r','r','x','indexed')")
        connection.execute("INSERT INTO repository_snapshots (id,repo_id,commit_hash,status,completed_at) VALUES ('s','r','abc','succeeded',CURRENT_TIMESTAMP)")
        connection.execute("UPDATE repos SET active_snapshot_id = 's' WHERE id = 'r'")
    session_id = create_session_record("r", "q", "a")
    with get_connection() as connection:
        assert connection.execute("SELECT snapshot_id FROM sessions WHERE id=?", (session_id,)).fetchone()[0] == "s"
