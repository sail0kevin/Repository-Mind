"""MCP Server 验收测试：覆盖仓库发现、5 个上下文工具、只读边界和真实 stdio 通信。"""
from __future__ import annotations

import json
import hashlib
import os
import sys
from pathlib import Path

import pytest

from service.core.embeddings.base import EmbeddingBatch, EmbeddingProvider
from service.core.embeddings.service import embed_snapshot_evidence
from service.core.retrieval import HybridRetriever
from service.core.retrieval.semantic import SemanticRetriever
from service.mcp_server import tools as mcp_tools
from service.mcp_server.envelope import MAX_QUERY_CHARS
from service.mcp_server.tools import (
    analyze_impact,
    find_related_tests,
    get_symbol,
    list_repositories,
    repo_overview,
    search_code,
)
from service.storage.evidence_store import (
    project_evidence_to_chunks,
    replace_all_snapshot_parse_results,
)
from service.storage.repository_store import create_repo_record, replace_file_records
from service.storage.snapshot_store import finish_snapshot, get_or_create_snapshot, publish_snapshot
from service.storage.sqlite_db import get_connection


@pytest.fixture
def anyio_backend() -> str:
    """只用 asyncio，避免 stdio 子进程在 trio 参数化下重复启动。"""
    return "asyncio"


class FakeProvider(EmbeddingProvider):
    """生成可复现的二维向量，让测试走真实向量存储和余弦检索。"""

    name = "fake"
    model = "fake-v1"
    enabled = True

    def embed(self, texts: list[str]) -> EmbeddingBatch:
        return EmbeddingBatch([[float(len(text)), 0.5] for text in texts], self.name, self.model)


def _seed_repo(tmp_path: Path, alias: str = "mcp-fixture", *, publish: bool = True) -> tuple[str, str, list[dict]]:
    """构造带调用关系、引用候选和测试文件的最小仓库。"""
    repo_path = tmp_path / alias
    repo_path.mkdir(parents=True, exist_ok=True)
    repo_id = create_repo_record(repo_path, alias, current_commit="a" * 40)
    snapshot, _ = get_or_create_snapshot(repo_id, "a" * 40, "main")
    snapshot_id = snapshot["id"]

    files = [
        {"relative_path": "src/auth.py", "language": "python", "file_type": "text",
         "is_binary": False, "is_test_file": False, "parse_status": "parsed"},
        {"relative_path": "src/login.py", "language": "python", "file_type": "text",
         "is_binary": False, "is_test_file": False, "parse_status": "parsed"},
        {"relative_path": "src/a_helper.py", "language": "python", "file_type": "text",
         "is_binary": False, "is_test_file": False, "parse_status": "parsed"},
        {"relative_path": "src/b_helper.py", "language": "python", "file_type": "text",
         "is_binary": False, "is_test_file": False, "parse_status": "parsed"},
        {"relative_path": "tests/test_auth.py", "language": "python", "file_type": "text",
         "is_binary": False, "is_test_file": True, "parse_status": "parsed"},
    ]
    replace_file_records(repo_id, files, snapshot_id=snapshot_id)

    with get_connection() as connection:
        rows = connection.execute(
            "SELECT id, relative_path FROM files WHERE snapshot_id = ?", (snapshot_id,)
        ).fetchall()
    file_id = {row["relative_path"]: row["id"] for row in rows}

    id_prefix = alias.replace("-", "_")

    def scoped(value: str) -> str:
        return f"{id_prefix}_{value}"

    definitions = [
        ("ev_auth", "src/auth.py", "function", "authenticate", 1, 2,
         "def authenticate(token):\n    return bool(token)"),
        ("ev_login", "src/login.py", "function", "login", 1, 2,
         "def login(token):\n    return authenticate(token)"),
        ("ev_helper_a", "src/a_helper.py", "function", "authenticate", 1, 2,
         "def authenticate(value):\n    return value == 'helper-a'"),
        ("ev_helper_b", "src/b_helper.py", "function", "format_name", 1, 2,
         "def format_name(value):\n    return value.strip()"),
        ("ev_test_auth", "tests/test_auth.py", "function", "test_authenticate", 1, 3,
         "def test_authenticate():\n    assert authenticate('token')\n    # reference candidate only"),
    ]
    evidence = [
        {
            "id": scoped(evidence_id),
            "logical_id": scoped(f"logical_{evidence_id}"),
            "identity_key": scoped(f"identity_{evidence_id}"),
            "snapshot_id": snapshot_id,
            "file_id": file_id[path],
            "unit_type": unit_type,
            "language": "python",
            "title": symbol_name,
            "start_line": start_line,
            "end_line": end_line,
            "content": content,
            "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "parser_name": "mcp-test",
            "parser_version": "1",
            "metadata": {"symbol_name": symbol_name},
        }
        for evidence_id, path, unit_type, symbol_name, start_line, end_line, content in definitions
    ]
    symbols = [
        {"id": scoped("sym_auth"), "logical_id": scoped("logical_sym_auth"), "identity_key": "symbol_auth",
         "snapshot_id": snapshot_id, "file_id": file_id["src/auth.py"], "evidence_id": scoped("ev_auth"),
         "qualified_name": "src.auth.authenticate", "name": "authenticate", "symbol_kind": "function",
         "start_line": 1, "end_line": 2},
        {"id": scoped("sym_login"), "logical_id": scoped("logical_sym_login"), "identity_key": "symbol_login",
         "snapshot_id": snapshot_id, "file_id": file_id["src/login.py"], "evidence_id": scoped("ev_login"),
         "qualified_name": "src.login.login", "name": "login", "symbol_kind": "function",
         "start_line": 1, "end_line": 2},
        {"id": scoped("sym_helper_auth"), "logical_id": scoped("logical_sym_helper_auth"), "identity_key": "symbol_helper_auth",
         "snapshot_id": snapshot_id, "file_id": file_id["src/a_helper.py"], "evidence_id": scoped("ev_helper_a"),
         "qualified_name": "src.a_helper.authenticate", "name": "authenticate", "symbol_kind": "function",
         "start_line": 1, "end_line": 2},
        {"id": scoped("sym_test_auth"), "logical_id": scoped("logical_sym_test_auth"), "identity_key": "symbol_test_auth",
         "snapshot_id": snapshot_id, "file_id": file_id["tests/test_auth.py"], "evidence_id": scoped("ev_test_auth"),
         "qualified_name": "tests.test_auth.test_authenticate", "name": "test_authenticate",
         "symbol_kind": "function", "start_line": 1, "end_line": 3},
    ]
    relations = [
        {"id": scoped("rel_login_auth"), "snapshot_id": snapshot_id, "file_id": file_id["src/login.py"],
         "source_symbol_id": scoped("sym_login"), "target_symbol_id": scoped("sym_auth"), "relation_type": "calls",
         "identity_key": "login_calls_auth", "observed": True, "inferred": False,
         "resolver_status": "resolved", "evidence_id": scoped("ev_login"), "line": 2,
         "extractor": "mcp-test", "extractor_version": "1"},
    ]
    replace_all_snapshot_parse_results(repo_id, snapshot_id, evidence, symbols, relations, [])
    project_evidence_to_chunks(repo_id, snapshot_id)
    if publish:
        publish_snapshot(repo_id, snapshot_id, "main", len(files))
    return repo_id, snapshot_id, evidence


def _assert_envelope(payload: dict, repo_id: str, snapshot_id: str) -> None:
    assert set(payload) == {"repo_id", "snapshot_id", "commit", "status", "data", "evidence", "limitations"}
    assert payload["repo_id"] == repo_id
    assert payload["snapshot_id"] == snapshot_id
    assert isinstance(payload["data"], dict)
    assert isinstance(payload["evidence"], list)
    assert isinstance(payload["limitations"], list)


def test_repository_discovery_returns_ids_without_local_paths(tmp_path: Path) -> None:
    indexed_repo_id, indexed_snapshot_id, _ = _seed_repo(tmp_path, "indexed")
    building_repo_id, _, _ = _seed_repo(tmp_path, "building-discovery", publish=False)

    result = list_repositories()

    assert result["status"] == "ok"
    assert result["repo_id"] == ""
    assert result["data"]["total"] == 2
    assert result["data"]["indexed_count"] == 1
    by_id = {item["repo_id"]: item for item in result["data"]["repositories"]}
    assert by_id[indexed_repo_id]["snapshot_id"] == indexed_snapshot_id
    assert by_id[indexed_repo_id]["indexed"] is True
    assert by_id[building_repo_id]["indexed"] is False
    serialized = json.dumps(result, ensure_ascii=False)
    assert str(tmp_path) not in serialized
    assert "repo_path" not in serialized


def test_active_snapshot_and_lexical_search_envelope(tmp_path: Path) -> None:
    repo_id, snapshot_id, _ = _seed_repo(tmp_path)

    overview = repo_overview(repo_id)
    result = search_code(repo_id, "authenticate", limit=5)

    _assert_envelope(overview, repo_id, snapshot_id)
    _assert_envelope(result, repo_id, snapshot_id)
    assert overview["status"] == "ok"
    assert result["status"] == "degraded"
    assert result["data"]["retrieval_mode"] == "lexical"
    assert result["evidence"]
    assert all(set(item) == {"evidence_id", "file_path", "start_line", "end_line", "snippet", "reason"}
               for item in result["evidence"])
    assert any("关键词" in item for item in result["limitations"])


def test_real_hybrid_search_uses_stored_vectors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_id, snapshot_id, evidence = _seed_repo(tmp_path)
    run = embed_snapshot_evidence(repo_id, snapshot_id, evidence, provider=FakeProvider())
    assert run.status == "ready" and run.stored == len(evidence)

    semantic = SemanticRetriever(query_embedder=lambda text: [float(len(text)), 0.5])
    monkeypatch.setattr(mcp_tools, "HybridRetriever", lambda: HybridRetriever(semantic=semantic))
    result = search_code(repo_id, "authenticate", limit=5)

    assert result["status"] == "ok"
    assert result["data"]["retrieval_mode"] == "hybrid"
    assert result["limitations"] == []
    assert result["evidence"]


def test_semantic_unavailable_and_zero_hit_are_distinct(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_id, snapshot_id, evidence = _seed_repo(tmp_path)
    unavailable = search_code(repo_id, "authenticate")
    assert unavailable["status"] == "degraded"
    assert unavailable["data"]["retrieval_mode"] == "lexical"
    assert any("不可用" in item for item in unavailable["limitations"])

    embed_snapshot_evidence(repo_id, snapshot_id, evidence, provider=FakeProvider())
    semantic = SemanticRetriever(
        query_embedder=lambda _text: [1.0, 0.5],
        search=lambda *_args, **_kwargs: [],
        availability=lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(mcp_tools, "HybridRetriever", lambda: HybridRetriever(semantic=semantic))
    zero_hit = search_code(repo_id, "authenticate")
    assert zero_hit["status"] == "degraded"
    assert zero_hit["data"]["retrieval_mode"] == "hybrid"
    assert any("没有返回任何结果" in item for item in zero_hit["limitations"])


def test_symbol_disambiguation_and_impact_evidence_tiers(tmp_path: Path) -> None:
    repo_id, snapshot_id, _ = _seed_repo(tmp_path)

    exact_symbol = get_symbol(repo_id, "src.auth.authenticate")
    symbol = get_symbol(repo_id, "authenticate")
    impact = analyze_impact(repo_id, "src.auth.authenticate")

    assert exact_symbol["data"]["match_method"] == "精确限定名匹配"
    assert symbol["status"] == "ok"
    assert symbol["data"]["match_method"] == "限定名后缀匹配"
    same_name = [item for item in symbol["data"]["candidates"] if item["name"] == "authenticate"]
    assert len(same_name) == 2
    assert symbol["data"]["symbol"]["file_path"] == "src/auth.py"
    assert impact["status"] == "ok"
    assert [item["file_path"] for item in impact["data"]["resolved_caller_evidence"]] == ["src/login.py"]
    assert [item["file_path"] for item in impact["data"]["reference_candidate_evidence"]] == ["tests/test_auth.py"]
    assert impact["data"]["definition_evidence"][0]["file_path"] == "src/auth.py"
    assert impact["data"]["resolved_relations"][0]["relation_type"] == "calls"
    _assert_envelope(impact, repo_id, snapshot_id)


def test_related_tests_is_read_only_and_explains_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_id, _, _ = _seed_repo(tmp_path)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("MCP 工具不得启动目标仓库子进程")

    monkeypatch.setattr(os, "system", forbidden)
    result = find_related_tests(repo_id, "authenticate")

    assert result["status"] == "ok"
    assert "tests/test_auth.py" in result["data"]["matched_test_files"]
    assert any("不会执行" in item for item in result["limitations"])


def test_snapshot_ownership_and_non_succeeded_snapshots_are_rejected(tmp_path: Path) -> None:
    repo_id, _, _ = _seed_repo(tmp_path, "primary")
    other_repo_id, other_snapshot_id, _ = _seed_repo(tmp_path, "other")
    assert search_code(repo_id, "auth", snapshot_id=other_snapshot_id)["status"] == "not_found"

    building_repo_id, building_snapshot_id, _ = _seed_repo(tmp_path, "building", publish=False)
    assert repo_overview(building_repo_id, building_snapshot_id)["status"] == "not_found"

    failed_repo_id, failed_snapshot_id, _ = _seed_repo(tmp_path, "failed", publish=False)
    finish_snapshot(failed_snapshot_id, "failed", error="expected test failure")
    assert repo_overview(failed_repo_id, failed_snapshot_id)["status"] == "not_found"
    assert other_repo_id != repo_id


def test_invalid_empty_and_oversized_parameters_are_bounded(tmp_path: Path) -> None:
    repo_id, _, _ = _seed_repo(tmp_path)
    assert search_code(repo_id, "   ")["status"] == "error"
    assert get_symbol(repo_id, "   ")["status"] == "error"
    assert analyze_impact(repo_id, "   ")["status"] == "error"

    oversized = search_code(repo_id, "authenticate " + "x" * 1000, limit=9999)
    invalid_limit = search_code(repo_id, "authenticate", limit="not-a-number")  # type: ignore[arg-type]
    negative_limit = search_code(repo_id, "authenticate", limit=-12)
    assert len(oversized["data"]["query"]) == MAX_QUERY_CHARS
    assert oversized["status"] in {"ok", "degraded"}
    assert len(invalid_limit["evidence"]) <= 10
    assert len(negative_limit["evidence"]) <= 1


@pytest.mark.anyio
async def test_real_stdio_server_lists_six_tools_and_calls_four(
    tmp_path: Path, temporary_database: Path
) -> None:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    repo_id, snapshot_id, _ = _seed_repo(tmp_path)
    backend_dir = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env.update({
        "REPOMIND_PATHS__DATA_DIR": str(temporary_database.parent),
        "REPOMIND_PATHS__DATABASE_PATH": str(temporary_database),
        "PYTHONIOENCODING": "utf-8",
    })
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "service.mcp_server"],
        env=env,
        cwd=str(backend_dir),
    )

    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            assert {tool.name for tool in listed.tools} == {
                "list_repositories", "repo_overview", "search_code", "get_symbol",
                "analyze_impact", "find_related_tests"
            }
            discovery = await session.call_tool("list_repositories", {})
            calls = [
                await session.call_tool("repo_overview", {"repo_id": repo_id}),
                await session.call_tool("search_code", {"repo_id": repo_id, "query": "authenticate"}),
                await session.call_tool("get_symbol", {"repo_id": repo_id, "symbol_query": "authenticate"}),
            ]

    assert not discovery.isError
    discovery_payload = discovery.structuredContent or json.loads(discovery.content[0].text)
    assert discovery_payload["data"]["repositories"][0]["repo_id"] == repo_id
    assert str(tmp_path) not in json.dumps(discovery_payload, ensure_ascii=False)
    for call in calls:
        assert not call.isError
        payload = call.structuredContent or json.loads(call.content[0].text)
        _assert_envelope(payload, repo_id, snapshot_id)
