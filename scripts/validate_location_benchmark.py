"""Validate a pinned, isolated code-location benchmark before it invokes a client.

The evaluator reads repository metadata only. It never runs target-repository code,
installs target dependencies, or writes into the target checkout.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from typing import Any


class BenchmarkValidationError(RuntimeError):
    """Raised when a benchmark setup could produce misleading results."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkValidationError(f"Cannot read JSON file {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise BenchmarkValidationError(f"JSON root in {path} must be an object.")
    return payload


def _required_string(payload: dict[str, Any], key: str, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkValidationError(f"{label}.{key} must be a non-empty string.")
    return value.strip()


def _resolve(base: Path, raw: str, label: str) -> Path:
    path = Path(raw).expanduser()
    resolved = path.resolve() if path.is_absolute() else (base / path).resolve()
    if not resolved.exists():
        raise BenchmarkValidationError(f"{label} does not exist: {resolved}")
    return resolved


def _git_output(repository: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository), *args],
        check=False,
        capture_output=True,
        encoding="utf-8",
        text=True,
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise BenchmarkValidationError(f"git {' '.join(args)} failed: {detail}")
    return completed.stdout.strip()


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _normalize_path(path: str) -> str:
    return str(Path(path).resolve()).replace("\\", "/").lower()


def _load_snapshot(database_path: Path, repo_id: str, snapshot_id: str) -> tuple[sqlite3.Row, sqlite3.Row]:
    try:
        with sqlite3.connect(str(database_path)) as connection:
            connection.row_factory = sqlite3.Row
            repo = connection.execute("SELECT * FROM repos WHERE id = ?", (repo_id,)).fetchone()
            snapshot = connection.execute(
                "SELECT * FROM repository_snapshots WHERE id = ? AND repo_id = ?",
                (snapshot_id, repo_id),
            ).fetchone()
    except sqlite3.Error as exc:
        raise BenchmarkValidationError(f"Cannot inspect benchmark database {database_path}: {exc}") from exc
    if repo is None:
        raise BenchmarkValidationError(f"repo_id={repo_id} is not present in the isolated database.")
    if snapshot is None:
        raise BenchmarkValidationError(
            f"snapshot_id={snapshot_id} does not belong to repo_id={repo_id} in the isolated database."
        )
    return repo, snapshot


def _validate_tasks(task_path: Path, repository: Path, commit: str) -> int:
    payload = _read_json(task_path)
    task_commit = _required_string(payload, "repository_commit", "tasks")
    if task_commit.lower() != commit.lower():
        raise BenchmarkValidationError(
            f"Task commit {task_commit} does not match manifest commit {commit}."
        )
    tasks = payload.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise BenchmarkValidationError("tasks.tasks must be a non-empty array.")
    task_type = payload.get("task_type", "multi_location_navigation")
    if task_type not in {"multi_location_navigation", "single_location_navigation"}:
        raise BenchmarkValidationError(
            "tasks.task_type must be multi_location_navigation or single_location_navigation."
        )
    minimum_locations = 1 if task_type == "single_location_navigation" else 2
    task_ids: set[str] = set()
    tree_paths = set(_git_output(repository, "ls-tree", "-r", "--name-only", commit).splitlines())
    for item in tasks:
        if not isinstance(item, dict):
            raise BenchmarkValidationError("Every task must be an object.")
        task_id = _required_string(item, "id", "task")
        if task_id in task_ids:
            raise BenchmarkValidationError(f"Duplicate task id: {task_id}")
        task_ids.add(task_id)
        if not isinstance(item.get("query"), str) or not item["query"].strip():
            raise BenchmarkValidationError(f"Task {task_id} has no query.")
        locations = item.get("expected_locations")
        groups = item.get("acceptable_location_groups")
        if groups is not None:
            if locations is not None:
                raise BenchmarkValidationError(
                    f"Task {task_id} must use either expected_locations or acceptable_location_groups, not both."
                )
            if not isinstance(groups, list) or len(groups) < minimum_locations:
                raise BenchmarkValidationError(
                    f"Task {task_id} must annotate at least {minimum_locations} acceptable location groups."
                )
            locations_to_validate = [location for group in groups for location in (group if isinstance(group, list) else [])]
            if any(not isinstance(group, list) or not group for group in groups):
                raise BenchmarkValidationError(f"Task {task_id} has an empty or invalid acceptable location group.")
        else:
            if not isinstance(locations, list) or len(locations) < minimum_locations:
                raise BenchmarkValidationError(
                    f"Task {task_id} must annotate at least {minimum_locations} expected_locations "
                    f"for {task_type}."
                )
            locations_to_validate = locations
        for location in locations_to_validate:
            if not isinstance(location, dict):
                raise BenchmarkValidationError(f"Task {task_id} has an invalid expected location.")
            relative_path = _required_string(location, "path", f"task {task_id} location")
            start_line = location.get("line_start")
            end_line = location.get("line_end", start_line)
            if not isinstance(start_line, int) or start_line < 1 or not isinstance(end_line, int) or end_line < start_line:
                raise BenchmarkValidationError(f"Task {task_id} has an invalid line range for {relative_path}.")
            if relative_path not in tree_paths:
                raise BenchmarkValidationError(
                    f"Task {task_id} references {relative_path}, which is absent at commit {commit}."
                )
    return len(tasks)


def validate_manifest(manifest_path: Path) -> dict[str, Any]:
    manifest = _read_json(manifest_path)
    base = manifest_path.parent
    benchmark_id = _required_string(manifest, "benchmark_id", "manifest")
    repository_config = manifest.get("repository")
    index_config = manifest.get("index")
    if not isinstance(repository_config, dict) or not isinstance(index_config, dict):
        raise BenchmarkValidationError("manifest.repository and manifest.index must be objects.")

    repository = _resolve(base, _required_string(repository_config, "path", "repository"), "repository.path")
    if not repository.is_dir():
        raise BenchmarkValidationError(f"repository.path is not a directory: {repository}")
    commit = _required_string(repository_config, "commit", "repository").lower()
    actual_commit = _git_output(repository, "rev-parse", "HEAD").lower()
    if actual_commit != commit:
        raise BenchmarkValidationError(
            f"Target checkout is at {actual_commit}, expected pinned commit {commit}."
        )

    database_path = _resolve(base, _required_string(index_config, "database_path", "index"), "index.database_path")
    data_dir = _resolve(base, _required_string(index_config, "data_dir", "index"), "index.data_dir")
    if not data_dir.is_dir():
        raise BenchmarkValidationError(f"index.data_dir is not a directory: {data_dir}")
    if not _is_within(database_path, data_dir):
        raise BenchmarkValidationError("index.database_path must live under index.data_dir for an isolated index.")
    repo_id = _required_string(index_config, "repo_id", "index")
    snapshot_id = _required_string(index_config, "snapshot_id", "index")
    repo, snapshot = _load_snapshot(database_path, repo_id, snapshot_id)
    if _normalize_path(repo["repo_path"]) != _normalize_path(str(repository)):
        raise BenchmarkValidationError(
            "The indexed repo_path does not match repository.path; refusing to use a different or implicit index."
        )
    if snapshot["status"] != "succeeded":
        raise BenchmarkValidationError("The benchmark snapshot must have status=succeeded.")
    if snapshot["commit_hash"].lower() != commit:
        raise BenchmarkValidationError(
            f"Indexed snapshot commit {snapshot['commit_hash']} does not match pinned commit {commit}."
        )

    task_path = _resolve(base, _required_string(manifest, "task_file", "manifest"), "task_file")
    if _is_within(task_path, repository):
        raise BenchmarkValidationError("task_file must live outside the target repository to avoid gold-label leakage.")
    task_count = _validate_tasks(task_path, repository, commit)
    return {
        "benchmark_id": benchmark_id,
        "repository_path": str(repository),
        "commit": commit,
        "database_path": str(database_path),
        "data_dir": str(data_dir),
        "repo_id": repo_id,
        "snapshot_id": snapshot_id,
        "task_file": str(task_path),
        "task_count": task_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = validate_manifest(args.manifest.resolve())
    except BenchmarkValidationError as exc:
        print(f"Benchmark preflight failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
