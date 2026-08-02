"""Calibrate RepoMind retrieval refusal on pinned positive and negative fixtures.

The runner creates an isolated SQLite index and invokes production ingest and
retrieval code. It never executes code from the target repository.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


class CalibrationError(RuntimeError):
    pass


def _git(repository: Path, *args: str) -> str:
    import subprocess

    result = subprocess.run(
        ["git", "-C", str(repository), *args], capture_output=True, text=True, encoding="utf-8", check=False
    )
    if result.returncode:
        raise CalibrationError((result.stderr or result.stdout).strip())
    return result.stdout.strip()


def _load_fixture(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload.get("queries"), list) or len(str(payload.get("snapshot_commit") or "")) != 40:
        raise CalibrationError(f"Invalid fixture: {path}")
    return payload


def _require_pinned_clean_checkout(repository: Path, commit: str) -> None:
    if not repository.is_dir():
        raise CalibrationError(f"Target repository does not exist: {repository}")
    if _git(repository, "rev-parse", "HEAD").lower() != commit.lower():
        raise CalibrationError("Target checkout is not at the fixture commit.")
    if _git(repository, "status", "--porcelain"):
        raise CalibrationError("Target checkout has uncommitted changes; use a clean benchmark worktree.")


def _safe_paths(items: list[dict]) -> list[str]:
    paths: list[str] = []
    for item in items:
        path = str(item.get("file_path") or "").replace("\\", "/")
        if path and not Path(path).is_absolute() and ":" not in path:
            paths.append(path)
    return paths


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _configure_embedding(mode: str, args: argparse.Namespace) -> dict[str, Any]:
    """Configure a real provider only for an explicitly requested Hybrid run."""
    from service.storage.secret_store import get_secret_store
    from service.storage.settings_store import set_setting

    if mode == "lexical":
        set_setting("embedding_provider", "disabled")
        return {
            "provider": "disabled",
            "base_url": None,
            "model": None,
            "max_input_characters": None,
            "batch_size": None,
        }

    if (
        args.embedding_provider != "openai_compatible"
        or not args.embedding_base_url
        or not args.embedding_model
        or not args.embedding_key_env
    ):
        raise CalibrationError(
            "Hybrid calibration requires --embedding-provider openai_compatible, "
            "--embedding-base-url, --embedding-model, and --embedding-key-env."
        )
    api_key = os.environ.get(args.embedding_key_env)
    if not api_key:
        raise CalibrationError(f"Hybrid calibration requires environment variable {args.embedding_key_env}.")
    set_setting("embedding_provider", args.embedding_provider)
    set_setting("embedding_base_url", args.embedding_base_url)
    set_setting("embedding_model", args.embedding_model)
    if args.embedding_max_input_characters is not None:
        if args.embedding_max_input_characters <= 0:
            raise CalibrationError("embedding max input characters must be positive.")
        set_setting("embedding_max_input_characters", args.embedding_max_input_characters)
    if args.embedding_batch_size is not None:
        if args.embedding_batch_size <= 0:
            raise CalibrationError("embedding batch size must be positive.")
        set_setting("embedding_batch_size", args.embedding_batch_size)
    get_secret_store().set("embedding_api_key", api_key)
    return {
        "provider": args.embedding_provider,
        "base_url": args.embedding_base_url,
        "model": args.embedding_model,
        "max_input_characters": args.embedding_max_input_characters,
        "batch_size": args.embedding_batch_size,
    }


def _validate_embedding_arguments(mode: str, args: argparse.Namespace) -> None:
    """Reject invalid Hybrid invocations before creating an isolated output directory."""
    if mode == "lexical":
        return
    if (
        args.embedding_provider != "openai_compatible"
        or not args.embedding_base_url
        or not args.embedding_model
        or not args.embedding_key_env
    ):
        raise CalibrationError(
            "Hybrid calibration requires --embedding-provider openai_compatible, "
            "--embedding-base-url, --embedding-model, and --embedding-key-env."
        )
    if not os.environ.get(args.embedding_key_env):
        raise CalibrationError(f"Hybrid calibration requires environment variable {args.embedding_key_env}.")
    if args.embedding_max_input_characters is not None and args.embedding_max_input_characters <= 0:
        raise CalibrationError("embedding max input characters must be positive.")
    if args.embedding_batch_size is not None and args.embedding_batch_size <= 0:
        raise CalibrationError("embedding batch size must be positive.")


def run_calibration(
    positive_path: Path,
    negative_path: Path,
    repository: Path,
    output_dir: Path,
    *,
    mode: str = "lexical",
    embedding_provider: str | None = None,
    embedding_base_url: str | None = None,
    embedding_model: str | None = None,
    embedding_key_env: str | None = None,
    embedding_max_input_characters: int | None = None,
    embedding_batch_size: int | None = None,
    hybrid_lexical_min_score: float | None = None,
    semantic_min_score: float | None = None,
) -> dict[str, Any]:
    positive = _load_fixture(positive_path)
    negative = _load_fixture(negative_path)
    if positive["snapshot_commit"] != negative["snapshot_commit"]:
        raise CalibrationError("Positive and negative fixtures must use the same pinned commit.")
    if mode not in {"lexical", "hybrid"}:
        raise CalibrationError(f"Unsupported calibration mode: {mode}")
    _require_pinned_clean_checkout(repository, positive["snapshot_commit"])
    config = argparse.Namespace(
        embedding_provider=embedding_provider,
        embedding_base_url=embedding_base_url,
        embedding_model=embedding_model,
        embedding_key_env=embedding_key_env,
        embedding_max_input_characters=embedding_max_input_characters,
        embedding_batch_size=embedding_batch_size,
    )
    _validate_embedding_arguments(mode, config)
    if output_dir.exists():
        raise CalibrationError(f"Refusing to reuse output directory: {output_dir}")
    output_dir.mkdir(parents=True)
    data_dir = output_dir / "data"
    data_dir.mkdir()

    sys.path.insert(0, str(BACKEND))
    from service.config import settings as settings_module
    from service.config.settings import Paths, Settings
    from service.core.ingest_service import ingest_repository_snapshot
    from service.core.retrieval import HybridRetriever
    from service.core.retrieval.relevance import RelevancePolicy
    from service.evaluation.retrieval_metrics import evaluate_rankings
    from service.storage.models import RepoCreateRequest
    from service.storage.secret_store import MemorySecretStore, set_secret_store
    from service.storage.settings_store import set_setting
    from service.storage.sqlite_db import reset_database_initialization
    from service.api.v1.repos import create_repository

    settings_module._settings = Settings(paths=Paths(data_dir=data_dir, database_path=data_dir / "repomind.sqlite3"))
    set_secret_store(MemorySecretStore())
    reset_database_initialization()
    started = time.monotonic()
    try:
        embedding = _configure_embedding(mode, config)
        registration = create_repository(RepoCreateRequest(repo_path=str(repository.resolve()), alias="relevance-calibration"))
        ingest = ingest_repository_snapshot(registration.repo_id, expected_commit=positive["snapshot_commit"])
        from service.core.vector_store import has_real_embeddings

        semantic_ready = has_real_embeddings(ingest.repo_id, ingest.snapshot_id)
        if mode == "hybrid" and not semantic_ready:
            raise CalibrationError("Hybrid calibration ingest completed without real embeddings.")
        if mode == "lexical" and semantic_ready:
            raise CalibrationError("Lexical calibration unexpectedly has real embeddings.")
        relevance = RelevancePolicy(
            hybrid_lexical_min_score=(
                hybrid_lexical_min_score if hybrid_lexical_min_score is not None else 31.4
            ),
            semantic_min_score=semantic_min_score if semantic_min_score is not None else 0.51,
        )
        retriever = HybridRetriever(relevance=relevance)
        results: list[dict[str, Any]] = []
        rankings: list[list[str]] = []
        relevant: list[list[str]] = []
        for fixture_type, fixture in (("positive", positive), ("negative", negative)):
            for query in fixture["queries"]:
                query_started = time.perf_counter()
                result = retriever.retrieve(ingest.repo_id, ingest.snapshot_id, query["query"], limit=8)
                if result.run.mode != mode:
                    raise CalibrationError(
                        f"{query['id']} used retrieval mode {result.run.mode!r}, expected {mode!r}."
                    )
                decision = result.run.relevance
                assert decision is not None
                paths = _safe_paths(result.items)
                record = {
                    "id": query["id"],
                    "type": fixture_type,
                    "query": query["query"],
                    "mode": result.run.mode,
                    "observation": decision.observation.to_dict(),
                    "outcome": decision.outcome,
                    "reason": decision.reason,
                    "accepted": decision.accepted,
                    "returned_evidence_count": len(result.items),
                    "ranked_paths": paths,
                    "latency_ms": round((time.perf_counter() - query_started) * 1000, 3),
                }
                results.append(record)
                if fixture_type == "positive":
                    rankings.append(paths)
                    relevant.append(list(query["relevant_paths"]))
        metrics = evaluate_rankings(rankings, relevant).to_dict()
        positives = [item for item in results if item["type"] == "positive"]
        negatives = [item for item in results if item["type"] == "negative"]
        summary = {
            "mode": mode,
            "embedding": embedding,
            "relevance": {
                "hybrid_lexical_min_score": relevance.hybrid_lexical_min_score,
                "semantic_min_score": relevance.semantic_min_score,
            },
            "snapshot_commit": positive["snapshot_commit"],
            "indexed_file_count": ingest.indexed_file_count,
            "chunk_count": ingest.chunk_count,
            "positive": {
                **metrics,
                "false_refusals": sum(not item["accepted"] for item in positives),
            },
            "negative": {
                "count": len(negatives),
                "refused_count": sum(not item["accepted"] for item in negatives),
                "rejection_accuracy": sum(not item["accepted"] for item in negatives) / len(negatives) if negatives else 0.0,
                "false_accepts": sum(item["accepted"] for item in negatives),
            },
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
        capture = {"summary": summary, "queries": results}
        _write_json(output_dir / "relevance-calibration.json", capture)
        return capture
    finally:
        reset_database_initialization()
        settings_module._settings = None
        set_secret_store(None)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--positive", type=Path, default=ROOT / "examples" / "benchmarks" / "backend-understanding-gold.json")
    parser.add_argument("--negative", type=Path, default=ROOT / "examples" / "benchmarks" / "backend-understanding-negative-v1.json")
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=("lexical", "hybrid"), default="lexical")
    parser.add_argument("--embedding-provider")
    parser.add_argument("--embedding-base-url")
    parser.add_argument("--embedding-model")
    parser.add_argument("--embedding-key-env")
    parser.add_argument("--embedding-max-input-characters", type=int)
    parser.add_argument("--embedding-batch-size", type=int)
    parser.add_argument("--hybrid-lexical-min-score", type=float)
    parser.add_argument("--semantic-min-score", type=float)
    args = parser.parse_args()
    try:
        result = run_calibration(
            args.positive,
            args.negative,
            args.repository,
            args.output_dir,
            mode=args.mode,
            embedding_provider=args.embedding_provider,
            embedding_base_url=args.embedding_base_url,
            embedding_model=args.embedding_model,
            embedding_key_env=args.embedding_key_env,
            embedding_max_input_characters=args.embedding_max_input_characters,
            embedding_batch_size=args.embedding_batch_size,
            hybrid_lexical_min_score=args.hybrid_lexical_min_score,
            semantic_min_score=args.semantic_min_score,
        )
    except CalibrationError as exc:
        print(f"Calibration failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
