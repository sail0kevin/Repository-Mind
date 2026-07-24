"""通过隔离 FastAPI/Trace 捕获内置 Demo 的真实修复后证据路径。

安全边界：脚本只复制、提交和静态索引 synthetic Demo 文件；绝不导入、运行或测试 Demo 代码，
也绝不读取默认 RepoMind 用户数据库或用户密钥存储。

本文件同时提供一个通用 Evidence Capture Runner（`--gold-file --repo-id --snapshot-id`），
用于驱动任意已注册并已完成 ingest 的仓库（不再局限于内置 3 题 Demo）。通用模式通过真实
HTTP 请求一个已经在运行的 RepoMind 后端（默认 http://127.0.0.1:8000/api/v1），复用与内置
Demo 完全相同的 Trace 采集与路径校验逻辑，因此产出结构（`ranked`/`evidence_paths`/`relevant`
等字段）与下游 `service/evaluation/*_metrics.py` 保持兼容。不带任何参数运行本脚本时，行为与
改造前完全一致（详见 `scripts/verify_capture_regression.py`）。
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
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


def _run_builtin_demo_capture() -> int:
    """注册、索引、提问和读取 Trace，全部成功后原子写入两个 post-fix 文件。

    这是脚本改造前唯一的行为；不带任何参数运行 `main()` 时会精确调用本函数，
    逐行未改动，用于保证 `scripts/verify_capture_regression.py` 的可复现性校验。
    """
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


class _HttpResponse:
    """包装 urllib 响应，使其满足 `_assert_response` 期待的 status_code/text/json() 接口。"""

    def __init__(self, status_code: int, body: bytes) -> None:
        self.status_code = status_code
        self._body = body

    @property
    def text(self) -> str:
        return self._body.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self._body)


def _http_call(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    json_body: dict[str, Any] | None = None,
    api_token: str | None = None,
) -> _HttpResponse:
    """对已运行的真实后端发起一次 HTTP 请求，返回结果，绝不吞掉真实的 HTTP 错误码。"""
    url = base_url.rstrip("/") + path
    data = json.dumps(json_body).encode("utf-8") if json_body is not None else None
    headers = {"Content-Type": "application/json"}
    if api_token:
        headers["X-RepoMind-API-Token"] = api_token
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return _HttpResponse(response.status, response.read())
    except urllib.error.HTTPError as exc:
        return _HttpResponse(exc.code, exc.read())


def _normalize_relative_path(raw_path: Any) -> str:
    """通用模式下只校验相对路径形状，不像内置 Demo 那样限制到固定的十文件集合。"""
    value = str(raw_path or "").strip().replace("\\", "/")
    path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    if not value or path.is_absolute() or windows_path.is_absolute() or windows_path.drive or ".." in path.parts:
        raise RuntimeError(f"API/Trace 返回了无效的相对路径：{value!r}")
    return value


def _fetch_known_paths(
    base_url: str,
    repo_id: str,
    snapshot_id: str | None,
    api_token: str | None,
) -> list[str]:
    """通过真实 GET /files 拉取目标 Snapshot 下全部已入库的相对路径。

    这份列表是任务完成率指标里"引用路径均能在目标仓库中找到对应文件"这一条
    的真实核验依据（而不是假设 answer.evidence 一定可信）。受 /files 接口单页
    上限约束，最多拉取 1000 条；超过该上限的仓库会在 limitations 中说明。
    """
    query = {"limit": 1000}
    if snapshot_id:
        query["snapshot_id"] = snapshot_id
    rows = _assert_response(
        _http_call(base_url, f"/repos/{repo_id}/files?{urllib.parse.urlencode(query)}", api_token=api_token),
        "list files",
    )
    return [_normalize_relative_path(row["relative_path"]) for row in rows]


def _run_generic_capture(args: argparse.Namespace) -> int:
    """驱动任意已注册且已完成 ingest 的仓库，产出与内置 Demo 结构兼容的 Evidence Capture。

    通过真实 HTTP 请求一个已经在运行的后端（不做注册/ingest，目标仓库必须提前
    ingest 完成），逐题调用 /ask 与 /traces，复用与内置 Demo 完全相同的 route/
    retrieval/synthesis 校验与 evidence 路径提取逻辑，因此产出的 `ranked`/
    `evidence_paths`/`relevant` 字段可以直接喂给 `report_retrieval_metrics.py`。
    另外记录每题的 `confidence`，并在顶层附上真实的 `known_paths` 文件清单，
    供任务完成率指标校验引用路径是否真实存在。
    """
    gold_path = Path(args.gold_file)
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    queries_spec = gold.get("queries")
    if not isinstance(queries_spec, list) or not queries_spec:
        raise RuntimeError(f"Gold 文件缺少非空 queries 数组：{gold_path}")

    base_url = args.base_url
    repo_id = args.repo_id
    snapshot_id = args.snapshot_id
    api_token = args.api_token or os.environ.get("REPOMIND_API_TOKEN")

    capture_queries: list[dict[str, Any]] = []
    retrieval_modes: set[str] = set()
    snapshot_commit: str | None = None

    for question in queries_spec:
        query_id = question["id"]
        expected_tools = list(question.get("expected_tools", []))
        relevant_paths = question.get("relevant_paths", [])

        ask_body: dict[str, Any] = {"question": question["query"], "limit": RESULT_LIMIT}
        if snapshot_id:
            ask_body["snapshot_id"] = snapshot_id
        answer = _assert_response(
            _http_call(base_url, f"/repos/{repo_id}/ask", method="POST", json_body=ask_body, api_token=api_token),
            f"ask {query_id}",
        )
        trace = _assert_response(
            _http_call(base_url, f"/repos/{repo_id}/traces/{answer['trace_id']}", api_token=api_token),
            f"trace {query_id}",
        )

        _single_step(trace, "route")
        retrieval = _single_step(trace, "retrieval")
        synthesis = _single_step(trace, "synthesis")
        tools = _trace_tools(trace)

        ranked = [_normalize_relative_path(entry.get("file_path")) for entry in retrieval.get("evidence_refs", [])]
        evidence_paths = [_normalize_relative_path(entry.get("file_path")) for entry in synthesis.get("evidence_refs", [])]
        if not ranked or not evidence_paths:
            raise RuntimeError(f"{query_id} 返回了空的 ranked 或 synthesis evidence，无法参与检索指标计算。")

        retrieval_modes.add(str(retrieval.get("output_summary", {}).get("mode")))
        snapshot_commit = answer.get("commit") or snapshot_commit

        capture_queries.append({
            "id": query_id,
            "query": question["query"],
            "route_tools": tools,
            "ranked": ranked,
            "evidence_paths": evidence_paths,
            "relevant": relevant_paths,
            "confidence": str(answer.get("confidence") or ""),
            "expected_tools": expected_tools,
        })
        if expected_tools and tools != expected_tools:
            print(
                f"警告：{query_id} 实际路由到 {tools}，gold 期望 {expected_tools}（已记录，未中断采集）。",
                file=sys.stderr,
            )

    known_paths = _fetch_known_paths(base_url, repo_id, snapshot_id, api_token)

    capture_payload = {
        "project": gold.get("name", gold_path.stem),
        "snapshot_commit": snapshot_commit,
        "mode": "/".join(sorted(retrieval_modes)) if retrieval_modes else "unknown",
        "source": f"real HTTP responses from a running backend at {base_url}",
        "query_count": len(capture_queries),
        "result_limit": RESULT_LIMIT,
        "known_paths": known_paths,
        "limitations": [
            "This capture evaluates cited evidence paths only; it does not judge answer semantics.",
            "Tool-routing mismatches against the gold file's expected_tools are logged as warnings, not hard failures.",
            "Latency is omitted because this script does not establish a controlled timing protocol.",
            "known_paths is capped at 1000 files by the /files endpoint; larger repositories are only partially covered.",
        ],
        "queries": capture_queries,
    }
    _assert_redacted(capture_payload, ROOT)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_temp = output_path.with_suffix(output_path.suffix + ".tmp")
    output_temp.write_text(json.dumps(capture_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(output_temp, output_path)

    print(output_path.as_posix())
    return 0


def _build_arg_parser() -> argparse.ArgumentParser:
    """构造命令行解析器；不带任何参数时保持与内置 Demo 采集完全一致的行为。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold-file", default=None, help="通用模式：评测集 JSON 路径（需包含非空 queries 数组）。")
    parser.add_argument("--repo-id", default=None, help="通用模式：已注册并已完成 ingest 的目标仓库 ID。")
    parser.add_argument("--snapshot-id", default=None, help="通用模式：目标 Snapshot ID；缺省沿用仓库当前 active 快照。")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/api/v1", help="通用模式：已运行后端的 API 根地址。")
    parser.add_argument("--api-token", default=None, help="通用模式：X-RepoMind-API-Token；缺省读取 REPOMIND_API_TOKEN 环境变量。")
    parser.add_argument("--output", default=None, help="通用模式：Capture JSON 输出路径（必填）。")
    return parser


def main() -> int:
    """无参数时精确复现内置 Demo 采集；带 --gold-file/--repo-id 时驱动任意已 ingest 的仓库。"""
    args = _build_arg_parser().parse_args()
    generic_flags = (args.gold_file, args.repo_id)
    if not any(generic_flags):
        return _run_builtin_demo_capture()
    if not all(generic_flags):
        raise SystemExit("通用模式需要同时提供 --gold-file 和 --repo-id。")
    if not args.output:
        raise SystemExit("通用模式需要提供 --output 采集结果写入路径。")
    return _run_generic_capture(args)


if __name__ == "__main__":
    raise SystemExit(main())
