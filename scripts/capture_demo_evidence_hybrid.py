"""在启用真实 Embedding 的前提下捕获内置 Demo 的 hybrid 双路证据。

用途：为"任务1 BM25 vs BM25+Embedding 对比实验"生成启用语义检索一路的真实 capture，
与纯词法基线 demo-evidence-capture-post-fix.json 并列对比。

安全边界：
- Embedding API Key 只从环境变量 REPOMIND_BENCH_EMBEDDING_KEY 或 gitignored 本地文件读取，
  绝不写入任何输出文件、绝不打印，落盘前经过脱敏断言强制拦截。
- 与 capture_demo_evidence.py 完全一致：只静态索引 synthetic Demo，绝不执行 Demo 代码，
  使用一次性临时 DB 与内存密钥存储，绝不触碰用户默认数据库或系统 DPAPI 密钥。

用法（PowerShell）：
    $env:REPOMIND_BENCH_EMBEDDING_KEY="<你的 embedding key>"
    # 可选：$env:REPOMIND_BENCH_EMBEDDING_BASE_URL / REPOMIND_BENCH_EMBEDDING_MODEL
    python scripts/capture_demo_evidence_hybrid.py
或把 Key 放进 gitignored 文件 bench-embedding.local.json 后直接运行本脚本。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

# 必须在导入 capture 模块（其模块级代码会清理 Embedding 环境变量）之前读取基准专用配置。
_REPO_ROOT = Path(__file__).resolve().parents[1]
_LOCAL_KEY_FILE = _REPO_ROOT / "bench-embedding.local.json"


def _load_embedding_config() -> dict[str, str]:
    """优先读环境变量；否则读 gitignored 本地 JSON。Key 绝不进入日志或输出。"""
    key = os.environ.get("REPOMIND_BENCH_EMBEDDING_KEY", "").strip()
    base_url = os.environ.get("REPOMIND_BENCH_EMBEDDING_BASE_URL", "").strip()
    model = os.environ.get("REPOMIND_BENCH_EMBEDDING_MODEL", "").strip()
    if not key and _LOCAL_KEY_FILE.is_file():
        payload = json.loads(_LOCAL_KEY_FILE.read_text(encoding="utf-8"))
        key = str(payload.get("api_key", "")).strip()
        base_url = base_url or str(payload.get("base_url", "")).strip()
        model = model or str(payload.get("model", "")).strip()
    return {
        "key": key,
        "base_url": base_url or "https://api.openai.com/v1",
        "model": model or "text-embedding-3-small",
    }


_CONFIG = _load_embedding_config()

# 导入基线采集模块，复用其 Demo 准备、路径归一化与 Trace 提取工具（其模块级代码会清空
# 生产 Embedding 环境变量，但不影响已读入 _CONFIG 的基准专用变量）。
import capture_demo_evidence as base  # noqa: E402


def _assert_no_key(payload: dict[str, Any], temp_root: Path) -> None:
    """在基线脱敏之上，额外强制拦截基准 Embedding Key 泄漏。"""
    serialized = json.dumps(payload, ensure_ascii=False).casefold()
    if _CONFIG["key"] and _CONFIG["key"].casefold() in serialized:
        raise RuntimeError("捕获结果包含 Embedding API Key，已阻止写盘。")
    base._assert_redacted(payload, temp_root)


# --- urllib 传输 shim ---------------------------------------------------------
# 背景：Ollama 的 OpenAI 兼容 /v1/embeddings 端点在 openai SDK(httpx 传输)下稳定
# 返回 502，但 curl / urllib 正常。这里用 urllib 实现一个最小客户端，通过 provider
# 现成的 client_factory 注入点替换传输层，逐条发送 string 输入以规避 Ollama 的批量/
# 传输兼容问题。仅用于本基准脚本，不改动生产代码。
import urllib.request as _urlreq  # noqa: E402


class _ShimItem:
    def __init__(self, index: int, embedding: list[float]) -> None:
        self.index = index
        self.embedding = embedding


class _ShimResponse:
    def __init__(self, data: list[_ShimItem]) -> None:
        self.data = data


class _ShimEmbeddings:
    def __init__(self, base_url: str, timeout: float) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    def create(self, *, model: str, input: Any, encoding_format: str | None = None) -> _ShimResponse:  # noqa: A002
        texts = [input] if isinstance(input, str) else list(input)
        items: list[_ShimItem] = []
        for i, text in enumerate(texts):
            body = json.dumps({"model": model, "input": text}).encode("utf-8")
            req = _urlreq.Request(
                self._base + "/embeddings", data=body, headers={"Content-Type": "application/json"}
            )
            with _urlreq.urlopen(req, timeout=self._timeout) as resp:
                payload = json.loads(resp.read())
            items.append(_ShimItem(i, [float(v) for v in payload["data"][0]["embedding"]]))
        return _ShimResponse(items)


class _ShimClient:
    def __init__(self, base_url: str, timeout: float) -> None:
        self.embeddings = _ShimEmbeddings(base_url, timeout)


def _urllib_client_factory(*, api_key: str, base_url: str, timeout: float) -> _ShimClient:
    return _ShimClient(base_url, timeout)


def _install_urllib_transport() -> None:
    """给 openai_compatible provider 注入 urllib 传输，绕开 httpx→Ollama 的 502。"""
    from service.core.embeddings import service as emb_service
    from service.core.embeddings.openai_compatible import OpenAICompatibleEmbeddingProvider

    original = emb_service.resolve_embedding_provider

    def patched():
        provider = original()
        if isinstance(provider, OpenAICompatibleEmbeddingProvider):
            provider._client_factory = _urllib_client_factory
        return provider

    emb_service.resolve_embedding_provider = patched


def main() -> int:
    """启用真实 Embedding，走 register→ingest→ask→trace，硬断言向量已存且检索走 hybrid。"""
    if not _CONFIG["key"]:
        raise SystemExit(
            "未找到 Embedding API Key。请设置环境变量 REPOMIND_BENCH_EMBEDDING_KEY，"
            f"或在 {_LOCAL_KEY_FILE.name} 写入 {{\"api_key\": \"...\"}}（该文件已被 gitignore）。"
        )

    import tempfile

    gold = json.loads(base.GOLD_PATH.read_text(encoding="utf-8"))
    if gold.get("snapshot_commit") != base.EXPECTED_COMMIT:
        raise RuntimeError("Gold fixture Snapshot 与固定 Demo commit 不一致。")
    relevant_by_id = {item["id"]: item["relevant_paths"] for item in gold["queries"]}
    known_paths = set(base.DEMO_FILES)

    output_path = _REPO_ROOT / "examples" / "benchmarks" / "demo-evidence-capture-hybrid.json"

    with tempfile.TemporaryDirectory(prefix="repomind-demo-hybrid-") as temp_value:
        temp_root = Path(temp_value)
        demo_repo = temp_root / "repomind-demo"
        data_dir = temp_root / "backend-data"
        commit = base._prepare_demo(demo_repo, temp_root / "git-home")
        if commit != base.EXPECTED_COMMIT:
            raise RuntimeError(f"Demo commit mismatch: expected {base.EXPECTED_COMMIT}, got {commit}.")

        from service.config import settings as settings_module
        from service.config.settings import Paths, Settings
        from service.storage.secret_store import MemorySecretStore, set_secret_store
        from service.storage.sqlite_db import reset_database_initialization

        data_dir.mkdir(parents=True)
        settings_module._settings = Settings(
            api_token=None,
            paths=Paths(data_dir=data_dir, database_path=data_dir / "repomind.sqlite3"),
        )
        # 注入含 Embedding Key 的内存密钥存储；绝不复用 Chat Key，绝不落盘。
        set_secret_store(MemorySecretStore(initial={"embedding_api_key": _CONFIG["key"]}))
        reset_database_initialization()

        from fastapi.testclient import TestClient
        from service.core.vector_store import has_real_embeddings
        from service.main import create_app
        from service.storage.settings_store import set_setting

        capture_queries: list[dict[str, Any]] = []
        try:
            with TestClient(create_app()) as client:
                # 应用启动并完成迁移后写入 Embedding 专属配置，使 ingest 阶段生成真实向量。
                set_setting("embedding_provider", "openai_compatible")
                set_setting("embedding_base_url", _CONFIG["base_url"])
                set_setting("embedding_model", _CONFIG["model"])
                # 注入 urllib 传输，绕开 httpx→Ollama 的 502（仅本基准脚本内生效）。
                _install_urllib_transport()

                registered = base._assert_response(
                    client.post("/api/v1/repos", json={
                        "repo_path": str(demo_repo),
                        "remote_url": None,
                        "branch": "main",
                        "alias": "RepoMind 内置 Demo (hybrid)",
                    }),
                    "register Demo",
                )
                repo_id = registered["repo_id"]

                ingest = base._assert_response(
                    client.post(f"/api/v1/repos/{repo_id}/ingest"), "start ingest",
                )
                job_id = ingest.get("job_id")
                if not job_id:
                    raise RuntimeError("Ingest 没有返回 job_id。")
                deadline = time.monotonic() + 1500
                while True:
                    job = base._assert_response(client.get(f"/api/v1/jobs/{job_id}"), "poll ingest")
                    if job["status"] in base.TERMINAL_JOB_STATUSES:
                        break
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Demo ingest 超过 180 秒未完成")
                    time.sleep(0.05)
                if job["status"] != "succeeded":
                    raise RuntimeError(f"Demo ingest {job['status']}: {job.get('error') or job.get('message')}")

                snapshots = base._assert_response(
                    client.get(f"/api/v1/repos/{repo_id}/snapshots"), "read snapshots",
                )
                active = next(item for item in snapshots["snapshots"] if item["is_active"])

                # 硬证明1：向量确实写入 evidence_embeddings，否则 Embedding 那路是空谈。
                if not has_real_embeddings(repo_id, active["snapshot_id"]):
                    raise RuntimeError(
                        "ingest 后没有真实向量：Embedding 调用可能失败（检查 Key/base_url/model 或网络）。"
                    )

                for question in base.QUESTIONS:
                    answer = base._assert_response(
                        client.post(f"/api/v1/repos/{repo_id}/ask", json={
                            "question": question["query"],
                            "limit": base.RESULT_LIMIT,
                            "snapshot_id": active["snapshot_id"],
                        }),
                        f"ask {question['id']}",
                    )
                    trace = base._assert_response(
                        client.get(f"/api/v1/repos/{repo_id}/traces/{answer['trace_id']}"),
                        f"trace {question['id']}",
                    )
                    retrieval = base._single_step(trace, "retrieval")
                    synthesis = base._single_step(trace, "synthesis")

                    # 硬证明2：检索计划确实走 hybrid 双路，而不是静默降级回 lexical。
                    actual_mode = retrieval.get("output_summary", {}).get("mode")
                    if actual_mode != "hybrid":
                        raise RuntimeError(
                            f"{question['id']} 检索 mode={actual_mode!r}，期望 'hybrid'（语义路未生效）。"
                        )

                    ranked = [
                        base._normalize_path(entry.get("file_path"), known_paths=known_paths)
                        for entry in retrieval.get("evidence_refs", [])
                    ]
                    evidence_paths = [
                        base._normalize_path(entry.get("file_path"), known_paths=known_paths)
                        for entry in synthesis.get("evidence_refs", [])
                    ]
                    if not ranked or not evidence_paths:
                        raise RuntimeError(f"{question['id']} 返回了空的 ranked 或 synthesis evidence。")

                    capture_queries.append({
                        "id": question["id"],
                        "query": question["query"],
                        "route_tools": base._trace_tools(trace),
                        "retrieval_mode": actual_mode,
                        "ranked": ranked,
                        "evidence_paths": evidence_paths,
                        "relevant": relevant_by_id[question["gold_id"]],
                    })

            capture_payload = {
                "project": "RepoMind bundled Demo (hybrid BM25+Embedding)",
                "snapshot_commit": commit,
                "mode": f"hybrid/bm25+embedding/{_CONFIG['model']}",
                "source": "real FastAPI registration/ingest/ask/trace responses with embeddings enabled",
                "baseline_capture": "demo-evidence-capture-post-fix.json",
                "query_count": len(capture_queries),
                "result_limit": base.RESULT_LIMIT,
                "limitations": [
                    "This capture evaluates cited evidence paths only; it does not judge answer semantics.",
                    "The bundled Demo contains three questions and is not a large-repository benchmark.",
                    "Embedding vectors are generated by an external provider; results depend on that model.",
                    "No target-repository code was executed and no Chat key was configured (rule fallback synthesis).",
                ],
                "queries": capture_queries,
            }
            _assert_no_key(capture_payload, temp_root)

            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_temp = output_path.with_suffix(output_path.suffix + ".tmp")
            output_temp.write_text(
                json.dumps(capture_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            os.replace(output_temp, output_path)
        finally:
            reset_database_initialization()
            settings_module._settings = None
            set_secret_store(None)

    print(output_path.relative_to(_REPO_ROOT).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
