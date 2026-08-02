"""Run an isolated, pinned RepoMind retrieval benchmark without target code execution."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import platform
import shutil
import subprocess
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
SENSITIVE_KEYS = {"api_key", "apikey", "authorization", "password", "secret", "token"}


class BenchmarkError(RuntimeError):
    """Raised when benchmark inputs or produced evidence are not reproducible."""


def _prepare_backend_imports() -> None:
    """Make the backend package available when this runner is invoked from the repo root."""
    backend_path = str(BACKEND)
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)


def _git(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *args], capture_output=True, text=True,
        encoding="utf-8", check=False,
    )
    if result.returncode:
        raise BenchmarkError((result.stderr or result.stdout).strip())
    return result.stdout.strip()


def _require_clean_pin(repository: Path, expected_commit: str) -> str:
    repository = repository.resolve()
    if not repository.is_dir():
        raise BenchmarkError(f"Target repository is not a directory: {repository}")
    actual = _git(repository, "rev-parse", "HEAD").lower()
    if actual != expected_commit.lower():
        raise BenchmarkError(f"Target is at {actual}, not pinned commit {expected_commit}.")
    if _git(repository, "status", "--porcelain"):
        raise BenchmarkError("Target checkout has uncommitted changes; create a clean benchmark worktree.")
    return actual


def _load_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise BenchmarkError("Manifest must be a JSON object.")
    target = payload.get("target")
    retrieval = payload.get("retrieval")
    if not isinstance(target, dict) or not isinstance(retrieval, dict):
        raise BenchmarkError("Manifest requires target and retrieval objects.")
    commit = str(target.get("commit") or "")
    if len(commit) != 40:
        raise BenchmarkError("Manifest target.commit must be a full 40-character SHA.")
    return payload


def _safe_relative_path(value: Any) -> str:
    path = str(value or "").strip().replace("\\", "/")
    posix = PurePosixPath(path)
    windows = PureWindowsPath(path)
    if not path or posix.is_absolute() or windows.is_absolute() or windows.drive or ".." in posix.parts:
        raise BenchmarkError(f"Unsafe relative path in API response: {path!r}")
    return path


def _single_step(trace: dict[str, Any], step_type: str) -> dict[str, Any]:
    matches = [step for step in trace.get("steps", []) if step.get("step_type") == step_type]
    if len(matches) != 1:
        raise BenchmarkError(f"Expected one {step_type} trace step, found {len(matches)}.")
    return matches[0]


def _trace_tools(trace: dict[str, Any]) -> list[str]:
    return [str(step["tool_name"]) for step in trace.get("steps", []) if step.get("step_type") == "tool"]


def _assert_redacted(payload: dict[str, Any], forbidden_values: list[str]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False)
    folded = serialized.casefold()
    for value in forbidden_values:
        forms = {
            value,
            value.replace("\\", "/"),
            value.replace("\\", "\\\\"),
        }
        if any(form.casefold() in folded for form in forms if form):
            raise BenchmarkError("Benchmark capture contains a local absolute path or credential.")

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                normalized = str(key).casefold()
                if normalized in SENSITIVE_KEYS or normalized.endswith("_api_key"):
                    raise BenchmarkError(f"Benchmark capture contains sensitive key {key!r}.")
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(payload)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _configure_embedding(mode: str, embedding: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    from service.storage.secret_store import get_secret_store
    from service.storage.settings_store import set_setting

    if mode == "lexical":
        set_setting("embedding_provider", "disabled")
        return {"provider": "disabled", "base_url": None, "model": None}
    provider = args.embedding_provider or embedding.get("provider")
    base_url = args.embedding_base_url or embedding.get("base_url")
    model = args.embedding_model or embedding.get("model")
    key_environment_variable = args.embedding_key_env or embedding.get("key_environment_variable")
    if provider != "openai_compatible" or not base_url or not model or not key_environment_variable:
        raise BenchmarkError("Hybrid mode requires openai_compatible provider, base URL, model, and key environment variable.")
    key = os.environ.get(str(key_environment_variable))
    if not key:
        raise BenchmarkError(f"Hybrid mode requires environment variable {key_environment_variable}.")
    set_setting("embedding_provider", provider)
    set_setting("embedding_base_url", str(base_url))
    set_setting("embedding_model", str(model))
    if args.embedding_max_input_characters is not None:
        set_setting("embedding_max_input_characters", args.embedding_max_input_characters)
    if args.embedding_batch_size is not None:
        if args.embedding_batch_size <= 0:
            raise BenchmarkError("embedding batch size must be positive.")
        set_setting("embedding_batch_size", args.embedding_batch_size)
    get_secret_store().set("embedding_api_key", key)
    return {
        "provider": provider,
        "base_url": str(base_url),
        "model": str(model),
        "max_input_characters": args.embedding_max_input_characters,
        "batch_size": args.embedding_batch_size,
    }


def _configure_reranker(mode: str, args: argparse.Namespace) -> dict[str, Any]:
    """Configure an optional local reranker and make the requested condition explicit."""
    from service.storage.settings_store import set_setting

    provider = str(getattr(args, "reranker_provider", "disabled") or "disabled").strip().lower()
    if provider not in {"disabled", "flag_embedding"}:
        raise BenchmarkError(f"Unsupported reranker provider: {provider!r}.")
    if provider != "disabled" and mode != "hybrid":
        raise BenchmarkError("A reranker benchmark requires hybrid retrieval mode.")
    model = str(getattr(args, "reranker_model", None) or "BAAI/bge-reranker-v2-m3")
    use_fp16 = bool(getattr(args, "reranker_use_fp16", False))
    candidate_limit = int(getattr(args, "reranker_candidate_limit", 50))
    if not 5 <= candidate_limit <= 50:
        raise BenchmarkError("reranker candidate limit must be between 5 and 50.")
    set_setting("reranker_provider", provider)
    set_setting("reranker_model", model)
    set_setting("reranker_use_fp16", use_fp16)
    set_setting("reranker_candidate_limit", candidate_limit)
    return {
        "provider": provider,
        "model": model if provider != "disabled" else None,
        "use_fp16": use_fp16,
        "candidate_limit": candidate_limit,
    }


def _rerank_summary(retrieval_step: dict[str, Any]) -> dict[str, Any]:
    rerank = retrieval_step.get("output_summary", {}).get("rerank")
    if not isinstance(rerank, dict) or not isinstance(rerank.get("applied"), bool):
        raise BenchmarkError("Retrieval trace does not contain a valid rerank audit summary.")
    candidate_count = rerank.get("candidate_count")
    if not isinstance(candidate_count, int) or candidate_count < 0:
        raise BenchmarkError("Retrieval trace has an invalid rerank candidate count.")
    return {"applied": rerank["applied"], "candidate_count": candidate_count}


def _validate_retrieval_configuration(retrieval: dict[str, Any]) -> None:
    """Reject manifests that claim parameters different from the active retriever defaults."""
    from service.core.retrieval.fusion import ReciprocalRankFusion
    from service.core.retrieval.planner import RetrievalPlanner
    from service.core.retrieval.structural import StructuralExpander

    planner = RetrievalPlanner()
    fusion = ReciprocalRankFusion()
    structural = StructuralExpander()
    expected = {
        "candidate_multiplier": planner.candidate_multiplier,
        "max_candidates": planner.max_candidates,
        "rrf_k": fusion.k,
        "structural_expansion": structural is not None,
    }
    for key, actual in expected.items():
        if retrieval.get(key) != actual:
            raise BenchmarkError(
                f"Manifest {key}={retrieval.get(key)!r} does not match active retriever value {actual!r}."
            )


def run_benchmark(manifest: dict[str, Any], repository: Path, output_dir: Path, mode: str, args: argparse.Namespace) -> dict[str, Path]:
    target = manifest["target"]
    retrieval = manifest["retrieval"]
    _prepare_backend_imports()
    _validate_retrieval_configuration(retrieval)
    expected_commit = str(target["commit"])
    commit = _require_clean_pin(repository, expected_commit)
    gold_path = ROOT / str(manifest["gold_file"])
    gold_bytes = gold_path.read_bytes()
    gold = json.loads(gold_bytes.decode("utf-8"))
    if gold.get("snapshot_commit") != commit or not isinstance(gold.get("queries"), list):
        raise BenchmarkError("Gold set does not match the pinned target commit.")
    configured_hash = str(manifest.get("gold_sha256") or "")
    gold_hash = hashlib.sha256(gold_bytes).hexdigest()
    if configured_hash not in {"", "<generated-and-validated-by-runner>", gold_hash}:
        raise BenchmarkError("Manifest gold_sha256 does not match the gold file.")
    if output_dir.exists():
        raise BenchmarkError(f"Refusing to reuse output directory: {output_dir}")
    data_dir = output_dir / "data"
    output_dir.mkdir(parents=True)
    data_dir.mkdir()

    from fastapi.testclient import TestClient
    from service.api.v1.repos import create_repository
    from service.config import settings as settings_module
    from service.config.settings import Paths, Settings
    from service.core.ingest_service import ingest_repository_snapshot
    from service.core.vector_store import has_real_embeddings
    from service.main import create_app
    from service.storage.models import RepoCreateRequest
    from service.storage.secret_store import MemorySecretStore, set_secret_store
    from service.storage.sqlite_db import reset_database_initialization

    settings_module._settings = Settings(paths=Paths(data_dir=data_dir, database_path=data_dir / "repomind.sqlite3"))
    set_secret_store(MemorySecretStore())
    reset_database_initialization()
    started = time.monotonic()
    try:
        embedding_info = _configure_embedding(mode, dict(manifest.get("embedding") or {}), args)
        reranker_info = _configure_reranker(mode, args)
        registration = create_repository(RepoCreateRequest(repo_path=str(repository.resolve()), alias="benchmark-target", remote_url=None, branch=None))
        ingest = ingest_repository_snapshot(registration.repo_id, expected_commit=commit)
        semantic_ready = has_real_embeddings(ingest.repo_id, ingest.snapshot_id)
        if mode == "hybrid" and not semantic_ready:
            raise BenchmarkError("Hybrid ingest completed without real embeddings.")
        if mode == "lexical" and semantic_ready:
            raise BenchmarkError("Lexical run unexpectedly has real embeddings.")

        queries: list[dict[str, Any]] = []
        with TestClient(create_app()) as client:
            files_response = client.get(f"/api/v1/repos/{ingest.repo_id}/files", params={"snapshot_id": ingest.snapshot_id, "limit": 1000})
            if files_response.status_code >= 400:
                raise BenchmarkError(f"Could not list indexed files: {files_response.text}")
            known_paths = [_safe_relative_path(row["relative_path"]) for row in files_response.json()]
            for question in gold["queries"]:
                call_started = time.perf_counter()
                answer_response = client.post(f"/api/v1/repos/{ingest.repo_id}/ask", json={"question": question["query"], "limit": int(retrieval["result_limit"]), "snapshot_id": ingest.snapshot_id})
                duration_ms = (time.perf_counter() - call_started) * 1000
                if answer_response.status_code >= 400:
                    raise BenchmarkError(f"Ask failed for {question['id']}: {answer_response.text}")
                answer = answer_response.json()
                trace_response = client.get(f"/api/v1/repos/{ingest.repo_id}/traces/{answer['trace_id']}")
                if trace_response.status_code >= 400:
                    raise BenchmarkError(f"Trace failed for {question['id']}: {trace_response.text}")
                trace = trace_response.json()
                retrieval_step = _single_step(trace, "retrieval")
                actual_mode = str(retrieval_step.get("output_summary", {}).get("mode") or "")
                if actual_mode != mode:
                    raise BenchmarkError(f"{question['id']} used retrieval mode {actual_mode!r}, expected {mode!r}.")
                rerank = _rerank_summary(retrieval_step)
                if reranker_info["provider"] != "disabled" and not rerank["applied"]:
                    raise BenchmarkError(f"{question['id']} did not apply the requested reranker.")
                queries.append({
                    "id": question["id"], "category": str(question.get("category") or "uncategorized"),
                    "query": question["query"],
                    "route_tools": _trace_tools(trace), "expected_tools": list(question.get("expected_tools", [])),
                    "ranked": [_safe_relative_path(item.get("file_path")) for item in retrieval_step.get("evidence_refs", [])],
                    "evidence_paths": [_safe_relative_path(item.get("file_path")) for item in _single_step(trace, "synthesis").get("evidence_refs", [])],
                    "relevant": list(question["relevant_paths"]), "confidence": str(answer.get("confidence") or ""),
                    "rerank": rerank,
                    "duration_ms": round(duration_ms, 3),
                })
        if any(not item["ranked"] for item in queries):
            raise BenchmarkError("At least one query returned no ranked evidence.")
        capture = {
            "project": manifest["benchmark_id"], "snapshot_commit": commit, "mode": mode,
            "source": "isolated real FastAPI registration/ingest/ask/trace responses",
            "query_count": len(queries), "result_limit": int(retrieval["result_limit"]),
            "known_paths": known_paths,
            "limitations": ["This capture measures evidence-path retrieval, not answer semantic correctness.", "Target repository code was not executed and no target dependencies were installed."],
            "queries": queries,
        }
        _assert_redacted(capture, [str(repository.resolve()), str(output_dir.resolve()), str(Path.home())])
        capture_path = output_dir / f"{mode}-capture.json"
        _write_json(capture_path, capture)
        runtime = {
            "benchmark_id": manifest["benchmark_id"], "target": {"repository_path": str(repository.resolve()), "commit": commit},
            "repomind_commit": _git(ROOT, "rev-parse", "HEAD"), "gold_sha256": gold_hash,
            "mode": mode, "embedding": embedding_info, "reranker": reranker_info, "retrieval": retrieval,
            "repo_id": ingest.repo_id, "snapshot_id": ingest.snapshot_id, "indexed_file_count": ingest.indexed_file_count,
            "chunk_count": ingest.chunk_count, "embedding_status": ingest.embedding_status,
            "python": sys.version, "platform": platform.platform(), "elapsed_seconds": round(time.monotonic() - started, 3),
        }
        runtime_path = output_dir / "runtime-manifest.local.json"
        _write_json(runtime_path, runtime)
    finally:
        reset_database_initialization()
        settings_module._settings = None
        set_secret_store(None)

    report_path = output_dir / f"{mode}-report.md"
    report_command = [sys.executable, str(ROOT / "scripts" / "report_retrieval_metrics.py"), str(capture_path), "--format", "markdown", "--output", str(report_path)]
    result = subprocess.run(report_command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if result.returncode:
        raise BenchmarkError(f"Report generation failed: {result.stderr or result.stdout}")
    return {"capture": capture_path, "report": report_path, "runtime": runtime_path}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=("lexical", "hybrid"), required=True)
    parser.add_argument("--embedding-provider")
    parser.add_argument("--embedding-base-url")
    parser.add_argument("--embedding-model")
    parser.add_argument("--embedding-key-env")
    parser.add_argument("--embedding-max-input-characters", type=int, default=None)
    parser.add_argument("--embedding-batch-size", type=int, default=None)
    parser.add_argument("--reranker-provider", choices=("disabled", "flag_embedding"), default="disabled")
    parser.add_argument("--reranker-model")
    parser.add_argument("--reranker-use-fp16", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--reranker-candidate-limit", type=int, default=50)
    args = parser.parse_args()
    try:
        paths = run_benchmark(_load_manifest(args.manifest), args.repository, args.output_dir, args.mode, args)
    except BenchmarkError as exc:
        print(f"Benchmark failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({key: str(value) for key, value in paths.items()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
