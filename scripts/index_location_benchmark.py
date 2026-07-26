"""Build one isolated RepoMind index for a pinned external benchmark checkout.

This runner intentionally uses the production repository registration and snapshot
ingest functions. It does not install dependencies, execute code, or write inside
the target checkout. Its only writes are the explicitly supplied RepoMind data
directory and database.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


class BenchmarkIndexError(RuntimeError):
    """Raised when the target checkout is unsafe or does not match its pin."""


def _git(repository: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository), *args],
        check=False,
        capture_output=True,
        encoding="utf-8",
        text=True,
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise BenchmarkIndexError(f"git {' '.join(args)} failed: {detail}")
    return completed.stdout.strip()


def _require_clean_pinned_checkout(repository: Path, expected_commit: str) -> str:
    if not repository.is_dir():
        raise BenchmarkIndexError(f"Repository path is not a directory: {repository}")
    actual_commit = _git(repository, "rev-parse", "HEAD").lower()
    if actual_commit != expected_commit.lower():
        raise BenchmarkIndexError(
            f"Target checkout is at {actual_commit}, expected pinned commit {expected_commit}."
        )
    if _git(repository, "status", "--porcelain"):
        raise BenchmarkIndexError("Target checkout has uncommitted changes; use a clean benchmark clone.")
    return actual_commit


def _validate_retry_database(database_path: Path, repository: Path, expected_commit: str) -> None:
    """Permit only a failed, single-repository benchmark ingest to be retried."""
    try:
        with sqlite3.connect(database_path) as connection:
            repos = connection.execute("SELECT repo_path FROM repos").fetchall()
            snapshots = connection.execute(
                "SELECT commit_hash, status FROM repository_snapshots"
            ).fetchall()
    except sqlite3.Error as exc:
        raise BenchmarkIndexError(f"Cannot inspect retry database {database_path}: {exc}") from exc
    normalized_repository = str(repository).replace("\\", "/").lower()
    if len(repos) != 1 or str(repos[0][0]).replace("\\", "/").lower() != normalized_repository:
        raise BenchmarkIndexError("Retry database is not isolated to this target repository.")
    if not snapshots or any(commit.lower() != expected_commit.lower() or status != "failed" for commit, status in snapshots):
        raise BenchmarkIndexError("Retry database must contain only failed snapshots for this pinned commit.")


def build_isolated_index(
    repository: Path,
    data_dir: Path,
    expected_commit: str,
    alias: str | None,
    retry_failed: bool,
) -> dict[str, Any]:
    """Register and synchronously ingest a checkout using a fresh, explicit data directory."""
    repository = repository.resolve()
    data_dir = data_dir.resolve()
    commit = _require_clean_pinned_checkout(repository, expected_commit)
    database_path = data_dir / "repomind.sqlite3"
    if database_path.exists() and not retry_failed:
        raise BenchmarkIndexError(
            f"Refusing to reuse an existing benchmark database: {database_path}. "
            "Choose a new data directory or pass --retry-failed for an isolated failed ingest."
        )
    if data_dir.exists() and any(data_dir.iterdir()) and not retry_failed:
        raise BenchmarkIndexError(
            f"Refusing to write into a non-empty benchmark data directory: {data_dir}."
        )
    if retry_failed:
        if not database_path.exists():
            raise BenchmarkIndexError("--retry-failed requires an existing isolated benchmark database.")
        _validate_retry_database(database_path, repository, commit)
    data_dir.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(BACKEND))
    from service.api.v1.repos import create_repository
    from service.config import settings as settings_module
    from service.config.settings import Paths, Settings
    from service.core.ingest_service import ingest_repository_snapshot
    from service.storage.models import RepoCreateRequest
    from service.storage.snapshot_store import get_snapshot
    from service.storage.sqlite_db import reset_database_initialization

    settings_module._settings = Settings(paths=Paths(data_dir=data_dir, database_path=database_path))
    reset_database_initialization()
    try:
        registration = create_repository(RepoCreateRequest(
            repo_path=str(repository),
            alias=alias or repository.name,
            remote_url=None,
            branch=None,
        ))
        result = ingest_repository_snapshot(registration.repo_id, expected_commit=commit)
        snapshot = get_snapshot(result.snapshot_id)
        if snapshot is None or snapshot["status"] != "succeeded" or snapshot["commit_hash"].lower() != commit:
            raise BenchmarkIndexError("Ingest completed without a succeeded snapshot at the pinned commit.")
        if _git(repository, "status", "--porcelain"):
            raise BenchmarkIndexError("Target checkout changed during indexing; index is not valid for the benchmark.")
        return {
            "repository_path": str(repository),
            "commit": commit,
            "data_dir": str(data_dir),
            "database_path": str(database_path),
            "repo_id": result.repo_id,
            "snapshot_id": result.snapshot_id,
            "indexed_file_count": result.indexed_file_count,
            "chunk_count": result.chunk_count,
            "embedding_status": result.embedding_status,
            "embedding_warning": result.embedding_warning,
        }
    finally:
        reset_database_initialization()
        settings_module._settings = None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True, type=Path)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--commit", required=True, help="Expected full Git commit SHA.")
    parser.add_argument("--alias", default=None)
    parser.add_argument("--retry-failed", action="store_true", help="Retry only an isolated failed ingest for this pin.")
    args = parser.parse_args()
    if len(args.commit.strip()) != 40:
        parser.error("--commit must be a full 40-character Git SHA.")
    try:
        result = build_isolated_index(args.repository, args.data_dir, args.commit, args.alias, args.retry_failed)
    except BenchmarkIndexError as exc:
        print(f"Benchmark indexing failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
