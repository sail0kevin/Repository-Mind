"""Profile a production RepoMind ingest against a clean, pinned checkout.

The target repository is only inspected through RepoMind's normal read-only
ingest path. All SQLite and vector writes go to the required, empty data
directory so a profile cannot alter the target checkout or a user's database.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.index_location_benchmark import BenchmarkIndexError, _require_clean_pinned_checkout


def _patch_timing(module: Any, name: str, measurements: dict[str, float]) -> None:
    """Time one production call without changing its inputs or result."""
    original: Callable[..., Any] = getattr(module, name)

    def timed(*args: Any, **kwargs: Any) -> Any:
        started = time.perf_counter()
        try:
            return original(*args, **kwargs)
        finally:
            measurements[name] = measurements.get(name, 0.0) + (time.perf_counter() - started)

    setattr(module, name, timed)


def _configure_embedding(args: argparse.Namespace) -> dict[str, Any]:
    """Configure an isolated profile database without persisting credentials."""
    from service.storage.secret_store import MemorySecretStore, set_secret_store
    from service.storage.settings_store import set_setting

    provider = str(args.embedding_provider or "disabled").strip().lower()
    if provider == "disabled":
        set_setting("embedding_provider", "disabled")
        set_secret_store(MemorySecretStore())
        return {"provider": "disabled", "base_url": None, "model": None}
    if provider != "openai_compatible":
        raise BenchmarkIndexError(f"Unsupported embedding provider: {provider!r}")
    if not args.embedding_base_url or not args.embedding_model:
        raise BenchmarkIndexError("An embedding base URL and model are required when embeddings are enabled.")
    if args.embedding_max_input_characters is not None and args.embedding_max_input_characters <= 0:
        raise BenchmarkIndexError("Embedding max input characters must be positive.")
    if args.embedding_batch_size is not None and args.embedding_batch_size <= 0:
        raise BenchmarkIndexError("Embedding batch size must be positive.")

    set_setting("embedding_provider", provider)
    set_setting("embedding_base_url", str(args.embedding_base_url))
    set_setting("embedding_model", str(args.embedding_model))
    if args.embedding_max_input_characters is not None:
        set_setting("embedding_max_input_characters", args.embedding_max_input_characters)
    if args.embedding_batch_size is not None:
        set_setting("embedding_batch_size", args.embedding_batch_size)
    set_secret_store(MemorySecretStore({"embedding_api_key": "local-profile"}))
    return {
        "provider": provider,
        "base_url": str(args.embedding_base_url),
        "model": str(args.embedding_model),
        "max_input_characters": args.embedding_max_input_characters,
        "batch_size": args.embedding_batch_size,
    }


def profile_ingest(repository: Path, data_dir: Path, commit: str, alias: str | None, args: argparse.Namespace) -> dict[str, Any]:
    """Create one isolated snapshot and return wall-clock stage measurements."""
    repository = repository.resolve()
    data_dir = data_dir.resolve()
    actual_commit = _require_clean_pinned_checkout(repository, commit)
    if not args.reuse_data_dir and data_dir.exists() and any(data_dir.iterdir()):
        raise BenchmarkIndexError(f"Profile data directory must be empty: {data_dir}")
    if args.reuse_data_dir and not (data_dir / "repomind.sqlite3").is_file():
        raise BenchmarkIndexError("A reusable profile data directory must contain repomind.sqlite3.")
    data_dir.mkdir(parents=True, exist_ok=True)

    backend = ROOT / "backend"
    sys.path.insert(0, str(backend))
    from service.api.v1.repos import create_repository
    from service.config import settings as settings_module
    from service.config.settings import Paths, Settings
    from service.core import ingest_service
    from service.storage.models import RepoCreateRequest
    from service.storage.repository_store import get_repo_record
    from service.storage.secret_store import set_secret_store
    from service.storage.snapshot_store import get_snapshot
    from service.storage.sqlite_db import reset_database_initialization

    measurements: dict[str, float] = {}
    originals: dict[str, Callable[..., Any]] = {}
    for name in (
        "scan_repository_files",
        "replace_file_records",
        "_capture_documents",
        "replace_all_snapshot_parse_results",
        "project_evidence_to_chunks",
        "project_symbols_to_code_graph",
        "build_catalog",
        "replace_snapshot_catalog",
        "_validate_snapshot",
        "publish_snapshot",
    ):
        originals[name] = getattr(ingest_service, name)
        _patch_timing(ingest_service, name, measurements)

    embedding_original = ingest_service.embed_snapshot_evidence
    embedding_result: dict[str, Any] = {}

    def timed_embedding(*args: Any, **kwargs: Any) -> Any:
        started = time.perf_counter()
        try:
            result = embedding_original(*args, **kwargs)
            embedding_result.update({
                "stored": result.stored,
                "reused": result.reused,
                "provider": result.provider,
                "model": result.model,
            })
            return result
        finally:
            measurements["embed_snapshot_evidence"] = (
                measurements.get("embed_snapshot_evidence", 0.0) + (time.perf_counter() - started)
            )

    ingest_service.embed_snapshot_evidence = timed_embedding

    registry = ingest_service.default_registry()
    original_parse_all = registry.parse_all

    def timed_parse_all(*args: Any, **kwargs: Any) -> Any:
        started = time.perf_counter()
        try:
            return original_parse_all(*args, **kwargs)
        finally:
            measurements["parse_all"] = measurements.get("parse_all", 0.0) + (time.perf_counter() - started)

    original_default_registry = ingest_service.default_registry
    ingest_service.default_registry = lambda: registry
    registry.parse_all = timed_parse_all

    database_path = data_dir / "repomind.sqlite3"
    settings_module._settings = Settings(paths=Paths(data_dir=data_dir, database_path=database_path))
    reset_database_initialization()
    started = time.perf_counter()
    try:
        embedding = _configure_embedding(args)
        if args.repo_id:
            registration = get_repo_record(args.repo_id)
            if registration is None:
                raise BenchmarkIndexError(f"Reusable profile repository does not exist: {args.repo_id}")
            if Path(str(registration["repo_path"])).resolve() != repository:
                raise BenchmarkIndexError("Reusable profile repository path does not match --repository.")
            repo_id = args.repo_id
        else:
            registration = create_repository(RepoCreateRequest(
                repo_path=str(repository), alias=alias or repository.name,
            ))
            repo_id = registration.repo_id
        result = ingest_service.ingest_repository_snapshot(repo_id, expected_commit=actual_commit)
        snapshot = get_snapshot(result.snapshot_id)
        if snapshot is None or snapshot["status"] != "succeeded":
            raise BenchmarkIndexError("Profile ingest did not publish a succeeded snapshot.")
        _require_clean_pinned_checkout(repository, actual_commit)
        elapsed = time.perf_counter() - started
        named_stages = {
            "scan": measurements.get("scan_repository_files", 0.0),
            "file_persistence": measurements.get("replace_file_records", 0.0),
            "capture": measurements.get("_capture_documents", 0.0),
            "parse": measurements.get("parse_all", 0.0),
            "facts_persistence": measurements.get("replace_all_snapshot_parse_results", 0.0),
            "chunk_projection": measurements.get("project_evidence_to_chunks", 0.0),
            "embedding": measurements.get("embed_snapshot_evidence", 0.0),
            "code_graph": measurements.get("project_symbols_to_code_graph", 0.0),
            "catalog": measurements.get("build_catalog", 0.0) + measurements.get("replace_snapshot_catalog", 0.0),
            "validation_publish": measurements.get("_validate_snapshot", 0.0) + measurements.get("publish_snapshot", 0.0),
        }
        return {
            "repository_path": str(repository),
            "commit": actual_commit,
            "data_dir": str(data_dir),
            "database_path": str(database_path),
            "repo_id": result.repo_id,
            "snapshot_id": result.snapshot_id,
            "indexed_file_count": result.indexed_file_count,
            "chunk_count": result.chunk_count,
            "embedding_status": result.embedding_status,
            "embedding_warning": result.embedding_warning,
            "embedding": embedding,
            "embedding_run": embedding_result,
            "elapsed_seconds": round(elapsed, 3),
            "stages_seconds": {name: round(value, 3) for name, value in named_stages.items()},
            "unattributed_seconds": round(max(0.0, elapsed - sum(named_stages.values())), 3),
        }
    finally:
        for name, original in originals.items():
            setattr(ingest_service, name, original)
        ingest_service.embed_snapshot_evidence = embedding_original
        ingest_service.default_registry = original_default_registry
        registry.parse_all = original_parse_all
        set_secret_store(None)
        reset_database_initialization()
        settings_module._settings = None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True, type=Path)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--alias", default=None)
    parser.add_argument("--reuse-data-dir", action="store_true",
                        help="Reuse an existing isolated profile database with --repo-id for a later snapshot.")
    parser.add_argument("--repo-id", default=None,
                        help="Existing repository ID within --data-dir; requires --reuse-data-dir.")
    parser.add_argument("--embedding-provider", choices=("disabled", "openai_compatible"), default="disabled")
    parser.add_argument("--embedding-base-url")
    parser.add_argument("--embedding-model")
    parser.add_argument("--embedding-max-input-characters", type=int, default=None)
    parser.add_argument("--embedding-batch-size", type=int, default=None)
    args = parser.parse_args()
    if len(args.commit.strip()) != 40:
        parser.error("--commit must be a full 40-character Git SHA.")
    if args.repo_id and not args.reuse_data_dir:
        parser.error("--repo-id requires --reuse-data-dir.")
    if args.reuse_data_dir and not args.repo_id:
        parser.error("--reuse-data-dir requires --repo-id.")
    try:
        result = profile_ingest(args.repository, args.data_dir, args.commit, args.alias, args)
    except BenchmarkIndexError as exc:
        print(f"Ingest profile failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
