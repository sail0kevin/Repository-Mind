"""通过隔离 FastAPI/Trace 捕获内置 Demo 的真实修复后证据路径。

安全边界：脚本只复制、提交和静态索引 synthetic Demo 文件；绝不导入、运行或测试 Demo 代码，
也绝不读取默认 RepoMind 用户数据库或用户密钥存储。
"""
from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
DEMO_SOURCE = ROOT / "demo" / "repomind-demo"
GOLD_PATH = ROOT / "examples" / "benchmarks" / "code-understanding-gold.json"
OUTPUT_PATH = ROOT / "examples" / "benchmarks" / "demo-evidence-capture-post-fix.json"
TRACE_OUTPUT_PATH = ROOT / "examples" / "outputs" / "repomind-demo-trace.post-fix.json"
EXPECTED_COMMIT = "8c5ac33542fbed5e117bfee19af1457e60bd166c"
RESULT_LIMIT = 8
TERMINAL_JOB_STATUSES = {"succeeded", "failed", "cancelled", "interrupted"}

# 与 electron-builder.yml 的打包过滤结果保持一致，避免开发目录中的 pyc 污染固定提交。
DEMO_FILES = (
    "README.md",
    "config.json",
    "expected/showcase.json",
    "repomind_demo/__init__.py",
    "repomind_demo/app/__init__.py",
    "repomind_demo/app/main.py",
    "repomind_demo/notifier.py",
    "repomind_demo/security_examples.py",
    "repomind_demo/service.py",
    "tests/test_greeting.py",
)

QUESTIONS = (
    {
        "id": "navigation-build-message",
        "gold_id": "navigation-build-message",
        "query": "GreetingService.build_message 方法是做什么的？",
        "expected_tools": [],
    },
    {
        "id": "security-review",
        "gold_id": "security-eval",
        "query": "security token 安全风险",
        "expected_tools": ["security_review"],
    },
    {
        "id": "impact-build-message",
        "gold_id": "impact-build-message",
        "query": "Changing GreetingService.build_message impact call chain and tests",
        "expected_tools": ["dependency_impact"],
    },
)

# 必须在导入 service 之前清除潜在网络模型凭据，并把模块搜索限定到仓库 backend。
for variable in (
    "REPOMIND_LLM_API_KEY",
    "REPOMIND_CHAT__API_KEY",
    "REPOMIND_EMBEDDING_API_KEY",
    "REPOMIND_EMBEDDING__API_KEY",
    "OPENAI_API_KEY",
):
    os.environ.pop(variable, None)
sys.path.insert(0, str(BACKEND))


def _run_git(repo: Path, *args: str, env: dict[str, str]) -> str:
    """以隔离配置运行 Git 元数据命令；该函数不会执行仓库程序或 Git hook。"""
    command = [
        "git",
        "-c", "core.autocrlf=false",
        "-c", "core.filemode=false",
        "-c", "commit.gpgsign=false",
        *args,
    ]
    result = subprocess.run(
        command,
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout.strip()


def _copy_packaged_fixture(target: Path) -> None:
    """仅复制打包清单中的十个 tracked 文件，不跟随开发目录生成物。"""
    target.mkdir(parents=True)
    for relative in DEMO_FILES:
        source = DEMO_SOURCE / Path(relative)
        if not source.is_file():
            raise FileNotFoundError(f"内置 Demo 资源缺失：{source}")
        destination = target / Path(relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)


def _prepare_demo(target: Path, git_home: Path) -> str:
    """复现打包 fixture 的固定身份、时间、分支和 commit，同时屏蔽全局 Git 配置。"""
    _copy_packaged_fixture(target)
    git_home.mkdir(parents=True)
    git_env = {
        **os.environ,
        "HOME": str(git_home),
        "USERPROFILE": str(git_home),
        "XDG_CONFIG_HOME": str(git_home / "xdg"),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "RepoMind Demo",
        "GIT_AUTHOR_EMAIL": "demo@repomind.local",
        "GIT_COMMITTER_NAME": "RepoMind Demo",
        "GIT_COMMITTER_EMAIL": "demo@repomind.local",
        "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
        "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
    }
    _run_git(target, "init", "--initial-branch=main", env=git_env)
    _run_git(target, "add", "--all", env=git_env)
    _run_git(
        target,
        "commit",
        "--no-gpg-sign",
        "--no-verify",
        "-m",
        "Create RepoMind built-in demo",
        env=git_env,
    )
    if _run_git(target, "status", "--porcelain", env=git_env):
        raise RuntimeError("Demo Git 工作树在固定提交后不是 clean 状态。")
    return _run_git(target, "rev-parse", "HEAD", env=git_env)


def _assert_response(response: Any, label: str) -> Any:
    """校验真实 HTTP 响应并返回 JSON；错误正文只用于本地失败诊断。"""
    if response.status_code >= 400:
        raise RuntimeError(f"{label} failed: HTTP {response.status_code}: {response.text}")
    return response.json()


def _normalize_path(raw_path: Any, *, known_paths: set[str]) -> str:
    """只归一化分隔符，并拒绝绝对路径、父目录跳转和非 fixture 路径。"""
    value = str(raw_path or "").strip().replace("\\", "/")
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or value not in known_paths:
        raise RuntimeError(f"API/Trace 返回了无效 Demo 相对路径：{value!r}")
    return value


def _trace_tools(trace: dict[str, Any]) -> list[str]:
    """按 Trace 原始 step 顺序提取实际执行的 Specialist Tool。"""
    return [
        str(step.get("tool_name"))
        for step in trace.get("steps", [])
        if step.get("step_type") == "tool"
    ]


def _single_step(trace: dict[str, Any], step_type: str) -> dict[str, Any]:
    """要求 route/retrieval/synthesis 关键步骤在 Trace 中恰好出现一次。"""
    matches = [step for step in trace.get("steps", []) if step.get("step_type") == step_type]
    if len(matches) != 1:
        raise RuntimeError(f"Trace 需要恰好一个 {step_type} step，实际为 {len(matches)}。")
    return matches[0]


def _assert_redacted(payload: dict[str, Any], temp_root: Path) -> None:
    """写盘前拒绝本机绝对路径、临时路径和常见凭据字段/值。"""
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    folded = serialized.casefold()
    forbidden_values = {
        str(temp_root),
        str(Path.home()),
        str(ROOT),
        os.environ.get("OPENAI_API_KEY", ""),
        os.environ.get("REPOMIND_API_TOKEN", ""),
    }
    forbidden_forms = {
        form.casefold()
        for value in forbidden_values
        if value
        for form in (value, value.replace("\\", "/"), value.replace("\\", "\\\\"))
    }
    if any(value in folded for value in forbidden_forms):
        raise RuntimeError("捕获结果包含本机路径或凭据值。")

    sensitive_keys = {"api_key", "apikey", "authorization", "password", "secret", "token"}

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                key_folded = str(key).casefold()
                if key_folded in sensitive_keys or key_folded.endswith("_api_key"):
                    raise RuntimeError(f"捕获结果包含敏感字段：{key}")
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(payload)


def main() -> int:
    """注册、索引、提问和读取 Trace，全部成功后原子写入两个 post-fix 文件。"""
    gold = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    if gold.get("snapshot_commit") != EXPECTED_COMMIT:
        raise RuntimeError("Gold fixture Snapshot 与固定 Demo commit 不一致。")
    relevant_by_id = {item["id"]: item["relevant_paths"] for item in gold["queries"]}
    known_paths = set(DEMO_FILES)

    with tempfile.TemporaryDirectory(prefix="repomind-demo-capture-") as temp_value:
        temp_root = Path(temp_value)
        demo_repo = temp_root / "repomind-demo"
        data_dir = temp_root / "backend-data"
        commit = _prepare_demo(demo_repo, temp_root / "git-home")
        if commit != EXPECTED_COMMIT:
            raise RuntimeError(f"Demo commit mismatch: expected {EXPECTED_COMMIT}, got {commit}.")

        # 在 create_app 之前注入一次性 DB 与内存空密钥存储，避免默认用户数据和 DPAPI。
        from service.config import settings as settings_module
        from service.config.settings import Paths, Settings
        from service.storage.secret_store import MemorySecretStore, set_secret_store
        from service.storage.sqlite_db import reset_database_initialization

        data_dir.mkdir(parents=True)
        settings_module._settings = Settings(
            api_token=None,
            paths=Paths(data_dir=data_dir, database_path=data_dir / "repomind.sqlite3"),
        )
        set_secret_store(MemorySecretStore())
        reset_database_initialization()

        from fastapi.testclient import TestClient
        from service.main import create_app

        capture_queries: list[dict[str, Any]] = []
        trace_questions: dict[str, Any] = {}
        try:
            with TestClient(create_app()) as client:
                registered = _assert_response(
                    client.post("/api/v1/repos", json={
                        "repo_path": str(demo_repo),
                        "remote_url": None,
                        "branch": "main",
                        "alias": "RepoMind 内置 Demo",
                    }),
                    "register Demo",
                )
                if registered.get("current_commit") != commit or registered.get("file_count") != len(DEMO_FILES):
                    raise RuntimeError("Demo 注册响应的 commit 或 file_count 不符合固定 fixture。")
                repo_id = registered["repo_id"]

                ingest = _assert_response(
                    client.post(f"/api/v1/repos/{repo_id}/ingest"),
                    "start ingest",
                )
                job_id = ingest.get("job_id")
                if not job_id:
                    raise RuntimeError("Ingest 没有返回 job_id。")
                deadline = time.monotonic() + 120
                while True:
                    job = _assert_response(client.get(f"/api/v1/jobs/{job_id}"), "poll ingest")
                    if job["status"] in TERMINAL_JOB_STATUSES:
                        break
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Demo ingest did not finish within 120 seconds")
                    time.sleep(0.05)
                if job["status"] != "succeeded":
                    raise RuntimeError(f"Demo ingest {job['status']}: {job.get('error') or job.get('message')}")

                snapshots = _assert_response(
                    client.get(f"/api/v1/repos/{repo_id}/snapshots"),
                    "read snapshots",
                )
                active_items = [item for item in snapshots["snapshots"] if item["is_active"]]
                if len(active_items) != 1:
                    raise RuntimeError("索引后需要恰好一个 active Snapshot。")
                active = active_items[0]
                if active["commit"] != commit or active["status"] != "succeeded":
                    raise RuntimeError("Active Snapshot 不是固定 Demo 的 succeeded 快照。")

                for question in QUESTIONS:
                    answer = _assert_response(
                        client.post(f"/api/v1/repos/{repo_id}/ask", json={
                            "question": question["query"],
                            "limit": RESULT_LIMIT,
                            "snapshot_id": active["snapshot_id"],
                        }),
                        f"ask {question['id']}",
                    )
                    trace = _assert_response(
                        client.get(f"/api/v1/repos/{repo_id}/traces/{answer['trace_id']}"),
                        f"trace {question['id']}",
                    )
                    if trace.get("snapshot_id") != active["snapshot_id"] or answer.get("commit") != commit:
                        raise RuntimeError(f"{question['id']} 的回答/Trace 未绑定固定 Snapshot。")

                    _single_step(trace, "route")
                    retrieval = _single_step(trace, "retrieval")
                    synthesis = _single_step(trace, "synthesis")
                    tools = _trace_tools(trace)
                    if tools != question["expected_tools"]:
                        raise RuntimeError(
                            f"{question['id']} routed to {tools}, expected {question['expected_tools']}"
                        )
                    if synthesis.get("output_summary", {}).get("generation_mode") != "rule_fallback":
                        raise RuntimeError(f"{question['id']} 未使用 no-key rule fallback。")

                    # ranked 来自检索 step 的真实发射顺序；evidence_paths 来自最终 synthesis，均保留重复项。
                    ranked = [
                        _normalize_path(entry.get("file_path"), known_paths=known_paths)
                        for entry in retrieval.get("evidence_refs", [])
                    ]
                    evidence_paths = [
                        _normalize_path(entry.get("file_path"), known_paths=known_paths)
                        for entry in synthesis.get("evidence_refs", [])
                    ]
                    response_paths = [
                        _normalize_path(entry.get("file_path"), known_paths=known_paths)
                        for entry in answer.get("evidence", [])
                    ]
                    if not ranked or not evidence_paths:
                        raise RuntimeError(f"{question['id']} 返回了空的 ranked 或 synthesis evidence。")
                    if evidence_paths != response_paths:
                        raise RuntimeError(f"{question['id']} 的 synthesis Trace 与 Ask Evidence 顺序不一致。")

                    capture_queries.append({
                        "id": question["id"],
                        "query": question["query"],
                        "route_tools": tools,
                        "ranked": ranked,
                        "evidence_paths": evidence_paths,
                        "relevant": relevant_by_id[question["gold_id"]],
                    })
                    trace_questions[question["id"]] = {
                        "question": question["query"],
                        "response": answer,
                        "trace": trace,
                    }

            capture_payload = {
                "project": "RepoMind bundled Demo",
                "snapshot_commit": commit,
                "mode": "lexical-only/no-key-fallback",
                "source": "real FastAPI registration/ingest/ask/trace responses",
                "source_trace": "examples/outputs/repomind-demo-trace.post-fix.json",
                "query_count": len(capture_queries),
                "pre_fix_capture": "demo-evidence-capture.json",
                "result_limit": RESULT_LIMIT,
                "limitations": [
                    "This capture evaluates cited evidence paths only; it does not judge answer semantics.",
                    "The bundled Demo contains three questions and is not a large-repository benchmark.",
                    "Latency is omitted because this script does not establish a controlled timing protocol.",
                    "This is a post-fix capture generated after Specialist Tool evidence was merged into synthesis.",
                    "No target-repository code was executed and no Chat or Embedding key was configured.",
                ],
                "queries": capture_queries,
            }
            trace_payload = {
                "format": "repomind.trace.v1",
                "demo": {
                    "alias": "RepoMind 内置 Demo",
                    "commit": commit,
                    "branch": "main",
                    "file_count": len(DEMO_FILES),
                },
                "retrieval_mode": "lexical_only",
                "generation_mode": "no_key_fallback",
                "result_limit": RESULT_LIMIT,
                "limitations": [
                    "No target-repository code was executed.",
                    "No Chat or Embedding key was used.",
                    "Security findings are static clues, not a complete audit.",
                ],
                "questions": trace_questions,
            }
            _assert_redacted(capture_payload, temp_root)
            _assert_redacted(trace_payload, temp_root)

            OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
            TRACE_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
            output_temp = OUTPUT_PATH.with_suffix(OUTPUT_PATH.suffix + ".tmp")
            trace_temp = TRACE_OUTPUT_PATH.with_suffix(TRACE_OUTPUT_PATH.suffix + ".tmp")
            output_temp.write_text(json.dumps(capture_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            trace_temp.write_text(json.dumps(trace_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(trace_temp, TRACE_OUTPUT_PATH)
            os.replace(output_temp, OUTPUT_PATH)
        finally:
            # 清除进程级单例，确保从其他 runner 导入执行时也不泄漏临时 DB/内存密钥状态。
            reset_database_initialization()
            settings_module._settings = None
            set_secret_store(None)

    print(OUTPUT_PATH.relative_to(ROOT).as_posix())
    print(TRACE_OUTPUT_PATH.relative_to(ROOT).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
