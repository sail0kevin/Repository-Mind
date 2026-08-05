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
    locate_code,
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


def test_search_with_no_evidence_returns_not_found_and_next_step(tmp_path: Path) -> None:
    repo_id, snapshot_id, _ = _seed_repo(tmp_path)

    result = search_code(repo_id, "qzjxvwpnkrmtafud")

    _assert_envelope(result, repo_id, snapshot_id)
    assert result["status"] == "not_found"
    assert result["evidence"] == []
    assert result["data"]["query"] == "qzjxvwpnkrmtafud"
    assert result["data"]["evidence_budget"]["item_count"] == 0
    assert any("get_symbol" in item for item in result["limitations"])


def test_locate_code_returns_independent_compact_candidates(tmp_path: Path) -> None:
    repo_id, snapshot_id, _ = _seed_repo(tmp_path)

    result = locate_code(
        repo_id,
        "Locate where authenticate is defined and where login calls authenticate.",
        limit=4,
    )

    _assert_envelope(result, repo_id, snapshot_id)
    assert result["status"] == "degraded"
    locations = result["data"]["locations"]
    assert locations
    assert all(set(item) == {"file_path", "start_line", "end_line", "evidence_id", "reason"}
               for item in locations)
    assert any(item["file_path"] == "src/auth.py" for item in locations)
    assert all(item["end_line"] - item["start_line"] <= 24 for item in locations)
    assert any("independent" in item for item in result["limitations"])


def test_locate_code_compact_mode_preserves_locations_with_less_context(tmp_path: Path) -> None:
    repo_id, snapshot_id, _ = _seed_repo(tmp_path)
    question = "Locate where authenticate is defined and where login calls authenticate."

    detailed = locate_code(repo_id, question, limit=4)
    compact = locate_code(repo_id, question, limit=4, compact=True)

    assert set(compact) == {
        "repo_id", "snapshot_id", "commit", "status", "locations", "retrieval_mode", "limitations"
    }
    assert compact["repo_id"] == repo_id
    assert compact["snapshot_id"] == snapshot_id
    assert compact["status"] == detailed["status"] == "degraded"
    expected_keys = {
        "path", "start_line", "end_line", "rank", "is_primary",
        "symbol", "kind", "match_basis",
    }
    assert all(set(item) == expected_keys for item in compact["locations"])
    assert [(item["path"], item["start_line"], item["end_line"]) for item in compact["locations"]] == [
        (item["file_path"], item["start_line"], item["end_line"])
        for item in detailed["data"]["locations"]
    ]
    assert [item["rank"] for item in compact["locations"]] == list(range(1, len(compact["locations"]) + 1))
    assert [item["is_primary"] for item in compact["locations"]].count(True) == 1
    assert compact["locations"][0]["is_primary"] is True
    assert all(item["kind"] in {"function", "method", "class", "module", "unknown"} for item in compact["locations"])
    assert all(item["match_basis"] in {"exact_symbol", "body_match", "symbol_match", "retrieval"} for item in compact["locations"])
    assert "question" not in compact
    assert all("evidence_id" not in item and "reason" not in item and "content" not in item for item in compact["locations"])
    assert len(json.dumps(compact, ensure_ascii=False)) < len(json.dumps(detailed, ensure_ascii=False)) * 0.95


def test_locate_code_merges_term_level_candidates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_id, snapshot_id, _ = _seed_repo(tmp_path)

    class FakeRetriever:
        def retrieve(self, _repo_id: str, _snapshot_id: str, query: str, _limit: int):
            items = []
            if query == "clarification approval":
                items = [{"chunk_id": "overview", "file_path": "src/overview.py", "start_line": 1,
                          "end_line": 1, "content": "# overview", "score": 1.0}]
            elif query == "clarification":
                items = [{"chunk_id": "clarify", "file_path": "src/workflow.py", "start_line": 10,
                          "end_line": 12, "content": "if needs_clarification:\n    ask_user()\n", "score": 2.0}]
            elif query == "approval":
                items = [{"chunk_id": "approve", "file_path": "src/workflow.py", "start_line": 30,
                          "end_line": 32, "content": "if needs_approval:\n    wait_for_human()\n", "score": 2.0}]
            return type("Result", (), {"items": items, "run": type("Run", (), {"mode": "lexical"})()})()

    monkeypatch.setattr(mcp_tools, "HybridRetriever", FakeRetriever)
    result = locate_code(repo_id, "clarification approval", limit=4)

    locations = result["data"]["locations"]
    assert any(item["start_line"] == 10 for item in locations)
    assert any(item["start_line"] == 30 for item in locations)
    assert result["snapshot_id"] == snapshot_id


def test_locate_code_prefers_executable_match_over_docstring(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_id, _, _ = _seed_repo(tmp_path)

    class FakeRetriever:
        def retrieve(self, _repo_id: str, _snapshot_id: str, _query: str, _limit: int):
            return type("Result", (), {"items": [{
                "chunk_id": "session_factory",
                "file_path": "src/api.py",
                "start_line": 1,
                "end_line": 6,
                "content": (
                    "def request(url):\n"
                    "    \"\"\"Create a temporary session for the public request.\n"
                    "    The session sends the request later.\n"
                    "    \"\"\"\n"
                    "    with Session() as session:\n"
                    "        return session.request(url)\n"
                ),
                "score": 2.0,
            }], "run": type("Run", (), {"mode": "lexical"})()})()

    monkeypatch.setattr(mcp_tools, "HybridRetriever", FakeRetriever)
    result = locate_code(repo_id, "Locate the temporary session for the public request", limit=1)

    location = result["data"]["locations"][0]
    assert location["file_path"] == "src/api.py"
    assert location["start_line"] <= 5 <= location["end_line"]


def test_locate_code_keeps_complete_question_definitions_before_word_recall(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_id, _, _ = _seed_repo(tmp_path)
    queried_terms: list[str] = []

    class FakeRetriever:
        def retrieve(self, _repo_id: str, _snapshot_id: str, query: str, _limit: int):
            queried_terms.append(query)
            if query == "Locate public request session preparation":
                items = [
                    {
                        "chunk_id": "public_request",
                        "file_path": "src/api.py",
                        "start_line": 20,
                        "end_line": 28,
                        "chunk_type": "function",
                        "content": "def request():\n    with Session() as session:\n        return session.request()\n",
                        "score": 2.0,
                    },
                    {
                        "chunk_id": "session_request",
                        "file_path": "src/sessions.py",
                        "start_line": 100,
                        "end_line": 110,
                        "chunk_type": "method",
                        "content": "def request(self):\n    prepared = self.prepare_request()\n    return self.send(prepared)\n",
                        "score": 1.9,
                    },
                    {
                        "chunk_id": "unrelated_class",
                        "file_path": "src/adapter.py",
                        "start_line": 1,
                        "end_line": 200,
                        "chunk_type": "class",
                        "content": "class Adapter:\n    def request(self):\n        return None\n",
                        "score": 99.0,
                    },
                ]
            else:
                items = []
            return type("Result", (), {"items": items, "run": type("Run", (), {"mode": "lexical"})()})()

    monkeypatch.setattr(mcp_tools, "HybridRetriever", FakeRetriever)
    result = locate_code(repo_id, "Locate public request session preparation", limit=4)

    assert queried_terms == ["Locate public request session preparation"]
    assert [(item["file_path"], item["start_line"]) for item in result["data"]["locations"]] == [
        ("src/api.py", 20), ("src/sessions.py", 100)
    ]


def test_locate_code_retrieves_each_explicit_behavior_clause(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_id, _, _ = _seed_repo(tmp_path)
    queries: list[str] = []

    class FakeRetriever:
        def retrieve(self, _repo_id: str, _snapshot_id: str, query: str, _limit: int):
            queries.append(query)
            if "first behavior" in query:
                items = [{
                    "chunk_id": "first", "file_path": "src/first.py", "start_line": 1, "end_line": 3,
                    "chunk_type": "function", "content": "def first_behavior():\n    return True\n", "score": 2.0,
                }]
            elif "second behavior" in query:
                items = [{
                    "chunk_id": "second", "file_path": "src/second.py", "start_line": 10, "end_line": 12,
                    "chunk_type": "function", "content": "def second_behavior():\n    return True\n", "score": 2.0,
                }]
            else:
                items = []
            return type("Result", (), {"items": items, "run": type("Run", (), {"mode": "lexical"})()})()

    monkeypatch.setattr(mcp_tools, "HybridRetriever", FakeRetriever)
    question = "Locate first behavior, and where second behavior is handled."
    result = locate_code(repo_id, question, limit=4)

    assert queries == [question, "Locate first behavior", "where second behavior is handled"]
    assert {(item["file_path"], item["start_line"]) for item in result["data"]["locations"]} == {
        ("src/first.py", 1), ("src/second.py", 10),
    }


def test_location_queries_expand_handler_to_adapter_without_repository_specific_terms() -> None:
    question = "Locate where a handler is selected for an outgoing URL."

    queries = mcp_tools._location_queries(question)

    assert queries == [question, "Locate where a adapter is selected for an outgoing URL."]


def test_location_terms_expand_handler_to_adapter_for_symbol_matching() -> None:
    assert "adapter" in mcp_tools._location_terms("Locate the selected transport handler")


def test_locate_code_retrieves_leading_behavior_clause_for_cross_file_location(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_id, _, _ = _seed_repo(tmp_path)

    class FakeRetriever:
        def retrieve(self, _repo_id: str, _snapshot_id: str, query: str, _limit: int):
            if query == "Locate the public helper that creates a temporary Session":
                items = [{
                    "chunk_id": "api_request", "file_path": "src/api.py", "start_line": 20, "end_line": 25,
                    "chunk_type": "function", "content": "def request():\n    with Session() as session:\n        return session.request()\n", "score": 2.0,
                }]
            elif query == "the Session.request method sends the prepared request":
                items = [{
                    "chunk_id": "session_request", "file_path": "src/sessions.py", "start_line": 50, "end_line": 58,
                    "chunk_type": "method", "content": "def request(self):\n    prepared = self.prepare_request()\n    return self.send(prepared)\n", "score": 2.0,
                }]
            else:
                items = []
            return type("Result", (), {"items": items, "run": type("Run", (), {"mode": "lexical"})()})()

    monkeypatch.setattr(mcp_tools, "HybridRetriever", FakeRetriever)
    question = (
        "Locate the public helper that creates a temporary Session, "
        "and the Session.request method sends the prepared request"
    )
    result = locate_code(repo_id, question, limit=4)

    locations = {(item["file_path"], item["start_line"]) for item in result["data"]["locations"]}
    assert {("src/api.py", 20), ("src/sessions.py", 50)} <= locations


def test_locate_code_promotes_qualified_symbol_with_two_question_clues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_id, snapshot_id, _ = _seed_repo(tmp_path)
    with get_connection() as connection:
        connection.execute(
            "UPDATE symbols SET qualified_name = ? WHERE qualified_name = ?",
            ("src.auth.Response.raise_for_status", "src.auth.authenticate"),
        )

    class FakeRetriever:
        def retrieve(self, _repo_id: str, _snapshot_id: str, _query: str, _limit: int):
            return type("Result", (), {"items": [{
                "chunk_id": "weak", "file_path": "src/noise.py", "start_line": 1, "end_line": 3,
                "chunk_type": "function", "content": "def status_report():\n    return None\n", "score": 99.0,
            }], "run": type("Run", (), {"mode": "lexical"})()})()

    monkeypatch.setattr(mcp_tools, "HybridRetriever", FakeRetriever)
    result = locate_code(repo_id, "Locate Response status error logic", snapshot_id, limit=1)

    assert result["data"]["locations"][0]["file_path"] == "src/auth.py"
    assert result["data"]["locations"][0]["start_line"] == 1
    assert result["data"]["locations"][0]["end_line"] == 2


def test_locate_code_upgrades_duplicate_lexical_candidate_with_symbol_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_id, snapshot_id, _ = _seed_repo(tmp_path)
    with get_connection() as connection:
        connection.execute(
            "UPDATE symbols SET qualified_name = ? WHERE qualified_name = ?",
            ("src.auth.Response.raise_for_status", "src.auth.authenticate"),
        )

    class FakeRetriever:
        def retrieve(self, _repo_id: str, _snapshot_id: str, _query: str, _limit: int):
            return type("Result", (), {"items": [{
                "chunk_id": "ev_auth", "file_path": "src/auth.py", "start_line": 1, "end_line": 2,
                "chunk_type": "function", "content": "def authenticate():\n    return True\n", "score": 1.0,
            }], "run": type("Run", (), {"mode": "lexical"})()})()

    monkeypatch.setattr(mcp_tools, "HybridRetriever", FakeRetriever)
    result = locate_code(repo_id, "Locate Response status error logic", snapshot_id, limit=1)

    assert result["data"]["locations"][0]["reason"] == "Parsed definition whose symbol name matches the question"


def test_locate_code_recalls_long_behavior_clues_before_common_words(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_id, _, _ = _seed_repo(tmp_path)
    queried_terms: list[str] = []

    class FakeRetriever:
        def retrieve(self, _repo_id: str, _snapshot_id: str, query: str, _limit: int):
            queried_terms.append(query)
            return type("Result", (), {"items": [], "run": type("Run", (), {"mode": "lexical"})()})()

    monkeypatch.setattr(mcp_tools, "HybridRetriever", FakeRetriever)
    locate_code(
        repo_id,
        "Locate one temporary session before sending the public request through a method.",
    )

    assert "temporary" in queried_terms
    assert queried_terms.index("temporary") < queried_terms.index("request")


def test_locate_code_includes_exact_symbol_boundaries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_id, _, _ = _seed_repo(tmp_path)

    class FakeRetriever:
        def retrieve(self, _repo_id: str, _snapshot_id: str, _query: str, _limit: int):
            return type("Result", (), {"items": [], "run": type("Run", (), {"mode": "lexical"})()})()

    monkeypatch.setattr(mcp_tools, "HybridRetriever", FakeRetriever)
    result = locate_code(repo_id, "Locate where login calls authenticate", limit=4)

    locations = result["data"]["locations"]
    assert any(item["file_path"] == "src/login.py" and item["start_line"] == 1 for item in locations)
    assert any(item["file_path"] == "src/auth.py" and item["start_line"] == 1 for item in locations)
    assert locations[0]["file_path"] == "src/login.py"


def test_locate_code_prefers_qualified_method_over_same_named_symbol(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_id, snapshot_id, _ = _seed_repo(tmp_path)
    with get_connection() as connection:
        connection.execute(
            "UPDATE symbols SET qualified_name = ? WHERE qualified_name = ?",
            ("src.auth.Session.authenticate", "src.auth.authenticate"),
        )

    class FakeRetriever:
        def retrieve(self, _repo_id: str, _snapshot_id: str, _query: str, _limit: int):
            return type("Result", (), {"items": [], "run": type("Run", (), {"mode": "lexical"})()})()

    monkeypatch.setattr(mcp_tools, "HybridRetriever", FakeRetriever)
    result = locate_code(repo_id, "Locate where Session authenticate is defined", snapshot_id, limit=1)

    assert result["data"]["locations"][0]["file_path"] == "src/auth.py"
    assert result["data"]["locations"][0]["start_line"] == 1


def test_locate_code_matches_import_facing_qualified_symbol_suffix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_id, snapshot_id, _ = _seed_repo(tmp_path)
    with get_connection() as connection:
        connection.execute(
            "UPDATE symbols SET qualified_name = ? WHERE qualified_name = ?",
            ("src.requests.api.request", "src.auth.authenticate"),
        )

    class FakeRetriever:
        def retrieve(self, _repo_id: str, _snapshot_id: str, _query: str, _limit: int):
            return type("Result", (), {"items": [], "run": type("Run", (), {"mode": "lexical"})()})()

    monkeypatch.setattr(mcp_tools, "HybridRetriever", FakeRetriever)
    result = locate_code(repo_id, "Locate requests.api.request", snapshot_id, limit=1)

    location = result["data"]["locations"][0]
    assert location["file_path"] == "src/auth.py"
    assert location["start_line"] == 1


def test_locate_code_prioritizes_method_under_explicit_class_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_id, snapshot_id, _ = _seed_repo(tmp_path)
    with get_connection() as connection:
        connection.execute(
            "UPDATE symbols SET qualified_name = ? WHERE qualified_name = ?",
            ("src.auth.Session.send", "src.auth.authenticate"),
        )
        connection.execute(
            "INSERT INTO symbols (id, logical_id, identity_key, snapshot_id, file_id, evidence_id, qualified_name, name, symbol_kind, start_line, end_line) "
            "SELECT ?, ?, ?, snapshot_id, file_id, evidence_id, ?, 'send', 'method', start_line, end_line FROM symbols WHERE qualified_name = ?",
            ("adapter_send", "adapter_send_logical", "adapter_send_identity", "src.auth.HTTPAdapter.send", "src.login.login"),
        )

    class FakeRetriever:
        def retrieve(self, _repo_id: str, _snapshot_id: str, _query: str, _limit: int):
            return type("Result", (), {"items": [], "run": type("Run", (), {"mode": "lexical"})()})()

    monkeypatch.setattr(mcp_tools, "HybridRetriever", FakeRetriever)
    result = locate_code(repo_id, "Locate where Session sends a prepared request", snapshot_id, limit=1)

    assert result["data"]["locations"][0]["file_path"] == "src/auth.py"
    assert result["data"]["locations"][0]["start_line"] == 1


def test_locate_code_prioritizes_explicit_qualified_method_over_class_helpers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_id, snapshot_id, _ = _seed_repo(tmp_path)
    with get_connection() as connection:
        connection.execute(
            "UPDATE symbols SET qualified_name = ?, symbol_kind = 'method' WHERE qualified_name = ?",
            ("src.auth.Session.request", "src.auth.authenticate"),
        )
        connection.execute(
            "INSERT INTO symbols (id, logical_id, identity_key, snapshot_id, file_id, evidence_id, qualified_name, name, symbol_kind, start_line, end_line) "
            "SELECT ?, ?, ?, snapshot_id, file_id, evidence_id, ?, 'prepare_request', 'method', start_line, end_line FROM symbols WHERE qualified_name = ?",
            ("prepare_request", "prepare_request_logical", "prepare_request_identity", "src.auth.Session.prepare_request", "src.login.login"),
        )

    class FakeRetriever:
        def retrieve(self, _repo_id: str, _snapshot_id: str, _query: str, _limit: int):
            return type("Result", (), {"items": [], "run": type("Run", (), {"mode": "lexical"})()})()

    monkeypatch.setattr(mcp_tools, "HybridRetriever", FakeRetriever)
    result = locate_code(
        repo_id,
        "Locate Session.request, which calls self.prepare_request",
        snapshot_id,
        limit=1,
    )

    assert result["data"]["locations"][0]["file_path"] == "src/auth.py"
    assert result["data"]["locations"][0]["start_line"] == 1


def _seed_call_relation_scenario(
    repo_id: str,
    snapshot_id: str,
    file_id: dict[str, str],
    methods: list[tuple[str, str, str, int, int]],
    resolved_calls: list[tuple[str, str]],
) -> None:
    """Replace the snapshot's symbols/relations with a small ``Class.method`` call graph.

    ``methods`` items are ``(short_id, file_path, qualified_name, start_line, end_line)``.
    ``resolved_calls`` items are ``(source_short_id, target_short_id)`` observed edges.
    """
    evidence = [
        {
            "id": f"{short_id}_ev", "logical_id": f"{short_id}_ev_logical",
            "identity_key": f"{short_id}_ev_identity", "snapshot_id": snapshot_id,
            "file_id": file_id[path], "unit_type": "method", "language": "python",
            "title": qualified_name.rsplit(".", 1)[-1], "start_line": start, "end_line": end,
            "content": f"def {qualified_name.rsplit('.', 1)[-1]}(self):\n    return None\n",
            "parser_name": "test", "parser_version": "1",
            "metadata": {"symbol_name": qualified_name.rsplit(".", 1)[-1]},
        }
        for short_id, path, qualified_name, start, end in methods
    ]
    symbols = [
        {
            "id": f"{short_id}_sym", "logical_id": f"{short_id}_sym_logical",
            "identity_key": f"{short_id}_sym_identity", "snapshot_id": snapshot_id,
            "file_id": file_id[path], "evidence_id": f"{short_id}_ev",
            "qualified_name": qualified_name, "name": qualified_name.rsplit(".", 1)[-1],
            "symbol_kind": "method", "start_line": start, "end_line": end,
        }
        for short_id, path, qualified_name, start, end in methods
    ]
    path_by_short = {short_id: path for short_id, path, _, _, _ in methods}
    relations = [
        {
            "id": f"rel_{source}_{target}", "snapshot_id": snapshot_id,
            "file_id": file_id[path_by_short[source]], "source_symbol_id": f"{source}_sym",
            "target_symbol_id": f"{target}_sym", "relation_type": "calls",
            "identity_key": f"{source}_calls_{target}", "observed": True, "inferred": False,
            "resolver_status": "resolved", "evidence_id": f"{source}_ev", "line": 1,
            "extractor": "test", "extractor_version": "1",
        }
        for source, target in resolved_calls
    ]
    replace_all_snapshot_parse_results(repo_id, snapshot_id, evidence, symbols, relations, [])


class _EmptyRetriever:
    def retrieve(self, _repo_id: str, _snapshot_id: str, _query: str, _limit: int):
        return type("Result", (), {"items": [], "run": type("Run", (), {"mode": "lexical"})()})()


def test_locate_code_boosts_resolved_call_neighbor_over_compact_distractor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A call-connected caller must survive the per-file cap over an unrelated compact match.

    ``configure`` (large span) and ``render`` (compact) are the two connected gold sites;
    ``reset`` is an equally strong lexical match but is not on the call graph. Without
    corroboration the compact ``reset`` would take the file's second slot and evict the
    real caller ``configure``.
    """
    repo_id, snapshot_id, _ = _seed_repo(tmp_path)
    with get_connection() as connection:
        file_id = {
            row["relative_path"]: row["id"]
            for row in connection.execute(
                "SELECT id, relative_path FROM files WHERE snapshot_id = ?", (snapshot_id,)
            ).fetchall()
        }
    _seed_call_relation_scenario(
        repo_id, snapshot_id, file_id,
        methods=[
            ("configure", "src/auth.py", "src.auth.Widget.configure", 1, 40),
            ("render", "src/auth.py", "src.auth.Widget.render", 45, 60),
            ("reset", "src/auth.py", "src.auth.Widget.reset", 65, 70),
        ],
        resolved_calls=[("configure", "render")],
    )

    monkeypatch.setattr(mcp_tools, "HybridRetriever", _EmptyRetriever)
    result = locate_code(
        repo_id, "Locate the widget configure step, the widget render step, and the widget reset step",
        snapshot_id, limit=2,
    )

    starts = {item["start_line"] for item in result["data"]["locations"]}
    assert starts == {1, 45}
    assert 65 not in starts


def test_locate_code_corroborates_callee_across_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A resolved callee ranks above an unrelated equally-strong match in another file."""
    repo_id, snapshot_id, _ = _seed_repo(tmp_path)
    with get_connection() as connection:
        file_id = {
            row["relative_path"]: row["id"]
            for row in connection.execute(
                "SELECT id, relative_path FROM files WHERE snapshot_id = ?", (snapshot_id,)
            ).fetchall()
        }
    _seed_call_relation_scenario(
        repo_id, snapshot_id, file_id,
        methods=[
            # anchor caller and its resolved callee (the gold), plus a compact distractor.
            ("dispatch", "src/login.py", "src.login.Client.dispatch", 1, 30),
            ("connect", "src/auth.py", "src.auth.Client.connect", 100, 140),
            ("noise", "src/b_helper.py", "src.b_helper.Client.connect", 5, 8),
        ],
        resolved_calls=[("dispatch", "connect")],
    )

    monkeypatch.setattr(mcp_tools, "HybridRetriever", _EmptyRetriever)
    result = locate_code(
        repo_id, "Locate the client dispatch stage and the client connect stage", snapshot_id, limit=6,
    )

    order = [(item["file_path"], item["start_line"]) for item in result["data"]["locations"]]
    assert ("src/auth.py", 100) in order
    assert order.index(("src/auth.py", 100)) < order.index(("src/b_helper.py", 5))


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
    assert symbol["evidence"][0]["snippet"]
    assert symbol["data"]["candidate_count"] == 3
    assert symbol["data"]["relation_count"] == 1
    assert impact["status"] == "ok"
    assert impact["data"]["evidence_groups"]["resolved_callers"] == ["mcp_fixture_ev_login"]
    assert impact["data"]["evidence_groups"]["reference_candidates"] == ["mcp_fixture_ev_test_auth"]
    assert impact["evidence"][0]["file_path"] == "src/auth.py"
    assert impact["data"]["resolved_relations"][0]["relation_type"] == "calls"
    _assert_envelope(impact, repo_id, snapshot_id)


def test_symbol_query_returns_static_call_candidates(tmp_path: Path) -> None:
    repo_id, snapshot_id, _ = _seed_repo(tmp_path)
    with get_connection() as connection:
        file_rows = connection.execute(
            "SELECT id, relative_path FROM files WHERE snapshot_id = ?", (snapshot_id,)
        ).fetchall()
    file_id = {row["relative_path"]: row["id"] for row in file_rows}
    evidence = [
        {
            "id": "wrapper_ev", "logical_id": "wrapper_logical", "identity_key": "wrapper_identity",
            "snapshot_id": snapshot_id, "file_id": file_id["src/login.py"], "unit_type": "function",
            "language": "python", "title": "public_search", "start_line": 10, "end_line": 11,
            "content": "def public_search(query):\n    return implementation(query)",
            "parser_name": "test", "parser_version": "1", "metadata": {"symbol_name": "public_search"},
        },
        {
            "id": "impl_ev", "logical_id": "impl_logical", "identity_key": "impl_identity",
            "snapshot_id": snapshot_id, "file_id": file_id["src/auth.py"], "unit_type": "function",
            "language": "python", "title": "implementation", "start_line": 10, "end_line": 11,
            "content": "def implementation(query):\n    return query", "parser_name": "test", "parser_version": "1",
            "metadata": {"symbol_name": "implementation"},
        },
    ]
    symbols = [
        {
            "id": "wrapper_sym", "logical_id": "wrapper_symbol_logical", "identity_key": "wrapper_symbol_identity",
            "snapshot_id": snapshot_id, "file_id": file_id["src/login.py"], "evidence_id": "wrapper_ev",
            "qualified_name": "api.public_search", "name": "public_search", "symbol_kind": "function",
            "start_line": 10, "end_line": 11,
        },
        {
            "id": "impl_sym", "logical_id": "impl_symbol_logical", "identity_key": "impl_symbol_identity",
            "snapshot_id": snapshot_id, "file_id": file_id["src/auth.py"], "evidence_id": "impl_ev",
            "qualified_name": "core.implementation", "name": "implementation", "symbol_kind": "function",
            "start_line": 10, "end_line": 11,
        },
    ]
    relations = [
        {
            "id": "call_rel", "snapshot_id": snapshot_id, "file_id": file_id["src/login.py"],
            "source_symbol_id": "wrapper_sym", "target_symbol_id": "impl_sym", "relation_type": "calls",
            "identity_key": "wrapper_calls", "observed": True, "inferred": True,
            "resolver_status": "resolved", "evidence_id": "wrapper_ev", "line": 11,
            "extractor": "test", "extractor_version": "1",
        },
    ]
    replace_all_snapshot_parse_results(repo_id, snapshot_id, evidence, symbols, relations, [])

    result = get_symbol(repo_id, "api.public_search")

    assert result["data"]["static_call_candidates"] == [{
        "name": "implementation", "qualified_name": "core.implementation", "file_path": "src/auth.py",
        "start_line": 10, "relation_type": "calls", "resolution": "static",
    }]
    assert any(item["evidence_id"] == "impl_ev" for item in result["evidence"])


def test_mcp_payloads_are_compact_but_keep_location_and_snapshot_proof(tmp_path: Path) -> None:
    repo_id, snapshot_id, _ = _seed_repo(tmp_path)

    search = search_code(repo_id, "authenticate")
    symbol = get_symbol(repo_id, "authenticate")
    impact = analyze_impact(repo_id, "authenticate")

    for payload in (search, symbol, impact):
        serialized = json.dumps(payload, ensure_ascii=False)
        assert len(serialized) < 9000
        assert payload["repo_id"] == repo_id
        assert payload["snapshot_id"] == snapshot_id
        assert payload["commit"] == "a" * 40
        assert all("absolute_path" not in item for item in payload["evidence"])
        assert all(item["file_path"] and item["start_line"] is not None for item in payload["evidence"])

    assert symbol["evidence"][0]["snippet"]
    assert set(impact["data"]["evidence_groups"]) == {
        "definition", "resolved_callers", "reference_candidates"
    }


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
    assert len(invalid_limit["evidence"]) <= 6
    assert len(negative_limit["evidence"]) <= 1


@pytest.mark.anyio
async def test_real_stdio_server_lists_seven_tools_and_calls_four(
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
                "locate_code", "analyze_impact", "find_related_tests"
            }
            discovery = await session.call_tool("list_repositories", {})
            calls = [
                await session.call_tool("repo_overview", {"repo_id": repo_id}),
                await session.call_tool("search_code", {"repo_id": repo_id, "query": "authenticate"}),
                await session.call_tool("locate_code", {"repo_id": repo_id, "question": "Locate authenticate"}),
                await session.call_tool("get_symbol", {"repo_id": repo_id, "symbol_query": "authenticate"}),
            ]
            compact_location = await session.call_tool(
                "locate_code", {"repo_id": repo_id, "question": "Locate authenticate", "compact": True}
            )
            missing_search = await session.call_tool(
                "search_code", {"repo_id": repo_id, "query": "qzjxvwpnkrmtafud"}
            )

    assert not discovery.isError
    discovery_payload = discovery.structuredContent or json.loads(discovery.content[0].text)
    assert discovery_payload["data"]["repositories"][0]["repo_id"] == repo_id
    assert str(tmp_path) not in json.dumps(discovery_payload, ensure_ascii=False)
    for call in calls:
        assert not call.isError
        payload = call.structuredContent or json.loads(call.content[0].text)
        _assert_envelope(payload, repo_id, snapshot_id)
    assert not compact_location.isError
    compact_payload = compact_location.structuredContent or json.loads(compact_location.content[0].text)
    assert compact_payload["snapshot_id"] == snapshot_id
    assert compact_payload["locations"]
    expected_keys = {
        "path", "start_line", "end_line", "rank", "is_primary",
        "symbol", "kind", "match_basis",
    }
    assert all(set(item) == expected_keys for item in compact_payload["locations"])
    assert [item["rank"] for item in compact_payload["locations"]] == list(range(1, len(compact_payload["locations"]) + 1))
    assert compact_payload["locations"][0]["is_primary"] is True
    missing_payload = missing_search.structuredContent or json.loads(missing_search.content[0].text)
    _assert_envelope(missing_payload, repo_id, snapshot_id)
    assert missing_payload["status"] == "not_found"
    assert missing_payload["evidence"] == []


@pytest.mark.anyio
async def test_coding_agent_stdio_profile_exposes_only_bound_compact_locator(
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
        "REPOMIND_MCP_REPO_ID": repo_id,
        "REPOMIND_MCP_SNAPSHOT_ID": snapshot_id,
        "PYTHONIOENCODING": "utf-8",
    })
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "service.mcp_server", "--profile", "coding-agent"],
        env=env,
        cwd=str(backend_dir),
    )

    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            assert [tool.name for tool in listed.tools] == ["locate_code"]
            locator = listed.tools[0]
            assert set(locator.inputSchema["properties"]) == {"question", "limit"}
            call = await session.call_tool("locate_code", {"question": "Locate authenticate"})

    assert not call.isError
    payload = call.structuredContent or json.loads(call.content[0].text)
    assert payload["repo_id"] == repo_id
    assert payload["snapshot_id"] == snapshot_id
    assert payload["locations"]
    expected_keys = {
        "path", "start_line", "end_line", "rank", "is_primary",
        "symbol", "kind", "match_basis",
    }
    assert all(set(item) == expected_keys for item in payload["locations"])
    assert payload["locations"][0]["rank"] == 1
    assert payload["locations"][0]["is_primary"] is True


@pytest.mark.anyio
async def test_coding_agent_location_1_profile_caps_bound_locator_to_one_location(
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
        "REPOMIND_MCP_REPO_ID": repo_id,
        "REPOMIND_MCP_SNAPSHOT_ID": snapshot_id,
        "PYTHONIOENCODING": "utf-8",
    })
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "service.mcp_server", "--profile", "coding-agent-location-1"],
        env=env,
        cwd=str(backend_dir),
    )

    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            assert [tool.name for tool in listed.tools] == ["locate_code"]
            locator = listed.tools[0]
            assert set(locator.inputSchema["properties"]) == {"question", "limit"}
            call = await session.call_tool(
                "locate_code", {"question": "Locate authenticate", "limit": 5}
            )

    assert not call.isError
    payload = call.structuredContent or json.loads(call.content[0].text)
    assert payload["repo_id"] == repo_id
    assert payload["snapshot_id"] == snapshot_id
    assert len(payload["locations"]) == 1
    assert set(payload["locations"][0]) == {"path", "start_line", "end_line"}


def _seed_methods_with_content(
    repo_id: str,
    snapshot_id: str,
    file_id: dict[str, str],
    methods: list[tuple[str, str, str, int, int, str]],
    resolved_calls: list[tuple[str, str]],
) -> None:
    """Like _seed_call_relation_scenario but accepts custom body content per method."""
    evidence = [
        {
            "id": f"{sid}_ev", "logical_id": f"{sid}_ev_logical",
            "identity_key": f"{sid}_ev_identity", "snapshot_id": snapshot_id,
            "file_id": file_id[path], "unit_type": "method", "language": "python",
            "title": qname.rsplit(".", 1)[-1], "start_line": start, "end_line": end,
            "content": content, "parser_name": "test", "parser_version": "1",
            "metadata": {"symbol_name": qname.rsplit(".", 1)[-1]},
        }
        for sid, path, qname, start, end, content in methods
    ]
    symbols = [
        {
            "id": f"{sid}_sym", "logical_id": f"{sid}_sym_logical",
            "identity_key": f"{sid}_sym_identity", "snapshot_id": snapshot_id,
            "file_id": file_id[path], "evidence_id": f"{sid}_ev",
            "qualified_name": qname, "name": qname.rsplit(".", 1)[-1],
            "symbol_kind": "method", "start_line": start, "end_line": end,
        }
        for sid, path, qname, start, end, _ in methods
    ]
    path_by_sid = {sid: path for sid, path, _, _, _, _ in methods}
    relations = [
        {
            "id": f"rel_{src}_{tgt}", "snapshot_id": snapshot_id,
            "file_id": file_id[path_by_sid[src]], "source_symbol_id": f"{src}_sym",
            "target_symbol_id": f"{tgt}_sym", "relation_type": "calls",
            "identity_key": f"{src}_calls_{tgt}", "observed": True, "inferred": False,
            "resolver_status": "resolved", "evidence_id": f"{src}_ev", "line": 1,
            "extractor": "test", "extractor_version": "1",
        }
        for src, tgt in resolved_calls
    ]
    replace_all_snapshot_parse_results(repo_id, snapshot_id, evidence, symbols, relations, [])


def test_locate_code_suppresses_trivial_dunder_boundary_in_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dunder methods with no executable content match must not crowd out real matches.

    ``__enter__`` and ``__exit__`` both match one term ("session") via the class
    component of their qualified name, but their bodies have no executable lines
    matching any query term.  Fix A guards the unconditional full-boundary append
    in the weak fallback pass: a single class-name-only term overlap with no body
    evidence must not earn a boundary entry that takes a per-file cap slot.
    ``install_transports`` has actual executable "https" / "transport" matches and
    must survive the per-file cap.
    """
    repo_id, snapshot_id, _ = _seed_repo(tmp_path)
    with get_connection() as connection:
        file_id = {
            row["relative_path"]: row["id"]
            for row in connection.execute(
                "SELECT id, relative_path FROM files WHERE snapshot_id = ?", (snapshot_id,)
            ).fetchall()
        }
    dunder_enter_body = "def __enter__(self):\n    return self\n"
    dunder_exit_body = "def __exit__(self, exc_type, exc_val, exc_tb):\n    pass\n"
    install_body = (
        "def install_transports(self):\n"
        "    handler = TransportHandler()\n"
        "    self.mount(\"https://\", handler)\n"
        "    self.mount(\"http://\", handler)\n"
        "    self.transport_handlers = [handler]\n"
    )
    _seed_methods_with_content(
        repo_id, snapshot_id, file_id,
        methods=[
            ("enter", "src/auth.py", "src.auth.Session.__enter__", 1, 2, dunder_enter_body),
            ("exit_", "src/auth.py", "src.auth.Session.__exit__", 4, 5, dunder_exit_body),
            ("install", "src/auth.py", "src.auth.Session.install_transports", 10, 24, install_body),
        ],
        resolved_calls=[],
    )

    monkeypatch.setattr(mcp_tools, "HybridRetriever", _EmptyRetriever)
    # lowercase "session" keeps explicit_class_names empty so class_match stays False
    result = locate_code(
        repo_id,
        "where does a session install the https transport handlers",
        snapshot_id,
        limit=3,
    )

    starts = {item["start_line"] for item in result["data"]["locations"]}
    assert 10 in starts, "install_transports must appear"
    assert 1 not in starts, "__enter__ must not take a per-file cap slot"
    assert 4 not in starts, "__exit__ must not take a per-file cap slot"


def test_locate_code_ranks_body_matching_anchor_over_name_only_anchor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Among tied anchors (same exact_symbol_match), the one with body content match wins.

    ``Session.request``, ``Session.prepare_request``, and ``Session.merge_settings``
    all qualify as 2-term anchors in the primary pass.  Without Fix B all boundary
    entries carry ``executable_matches=0`` and ``symbol_compactness`` decides,
    evicting the longest method (``Session.request``, which contains the real call
    site) in favour of the shorter ``Session.prepare_request``.  Fix B propagates
    the body-line executable match count so ``Session.request`` (body references
    "settings" / "environment") outranks ``Session.prepare_request`` (body has no
    such terms).
    """
    repo_id, snapshot_id, _ = _seed_repo(tmp_path)
    with get_connection() as connection:
        file_id = {
            row["relative_path"]: row["id"]
            for row in connection.execute(
                "SELECT id, relative_path FROM files WHERE snapshot_id = ?", (snapshot_id,)
            ).fetchall()
        }
    request_body = (
        "def request(self, method, url):\n"
        "    prep = self.prepare_request(method, url)\n"
        "    settings = self.merge_settings(prep)\n"
        "    environment_settings = settings.copy()\n"
        "    resp = self.send(prep, **environment_settings)\n"
        "    return resp\n"
    )
    prepare_body = (
        "def prepare_request(self, method, url):\n"
        "    p = PreparedRequest()\n"
        "    p.prepare_method(method)\n"
        "    p.prepare_url(url)\n"
        "    return p\n"
    )
    merge_body = (
        "def merge_settings(self, request):\n"
        "    environment = get_environ_proxies(request.url)\n"
        "    merged = {**request.settings, **environment}\n"
        "    return merged\n"
    )
    _seed_methods_with_content(
        repo_id, snapshot_id, file_id,
        methods=[
            ("request", "src/login.py", "src.login.Session.request", 10, 55, request_body),
            ("prepare", "src/login.py", "src.login.Session.prepare_request", 60, 75, prepare_body),
            ("merge", "src/login.py", "src.login.Session.merge_settings", 80, 92, merge_body),
        ],
        resolved_calls=[("request", "merge")],
    )

    monkeypatch.setattr(mcp_tools, "HybridRetriever", _EmptyRetriever)
    # "merges" != identifier-split "merge", so all three stay tied at exact_symbol_match=2
    result = locate_code(
        repo_id,
        "where does session request merges environment settings",
        snapshot_id,
        limit=3,
    )

    starts = {item["start_line"] for item in result["data"]["locations"]}
    assert 10 in starts, "Session.request (gold container) must appear"
    assert 80 in starts, "Session.merge_settings (gold definition) must appear"
    assert 60 not in starts, "Session.prepare_request (name-only anchor) must not take a slot"


def test_locate_code_allows_three_slots_per_file_for_large_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The leading (highest-ranked) file gets a cap of 3 when limit >= 6.

    Compound queries often target multiple sites inside one large module.  The
    leading file — the one whose first chunk ranks highest — is allowed a third
    slot so those sites are not evicted by the diversity cap.  All other files
    remain capped at 2, preserving cross-file diversity.  With limit=4 even the
    leading file stays at 2.
    """
    repo_id, snapshot_id, _ = _seed_repo(tmp_path)
    with get_connection() as connection:
        file_id = {
            row["relative_path"]: row["id"]
            for row in connection.execute(
                "SELECT id, relative_path FROM files WHERE snapshot_id = ?", (snapshot_id,)
            ).fetchall()
        }
    setup_body = (
        "def setup_environment(self):\n"
        "    self.proxies = {}\n"
        "    self.cert = None\n"
        "    self.verify = True\n"
    )
    merge_body = (
        "def merge_environment_settings(self, url, proxies, verify, cert):\n"
        "    env_proxies = get_environ_proxies(url)\n"
        "    merged_proxies = merge_setting(proxies, env_proxies)\n"
        "    merged_verify = merge_setting(verify, self.verify)\n"
        "    merged_cert = merge_setting(cert, self.cert)\n"
        "    return {'proxies': merged_proxies, 'verify': merged_verify, 'cert': merged_cert}\n"
    )
    send_body = (
        "def send(self, request, proxies=None, cert=None, verify=True):\n"
        "    settings = self.merge_environment_settings(request.url, proxies, verify, cert)\n"
        "    adapter = self.get_adapter(url=request.url)\n"
        "    return adapter.send(request, **settings)\n"
    )
    _seed_methods_with_content(
        repo_id, snapshot_id, file_id,
        methods=[
            ("setup", "src/auth.py", "src.auth.Session.setup_environment", 10, 25, setup_body),
            ("merge", "src/auth.py", "src.auth.Session.merge_environment_settings", 30, 65, merge_body),
            ("send", "src/auth.py", "src.auth.Session.send", 70, 110, send_body),
        ],
        resolved_calls=[("send", "merge")],
    )

    # FakeRetriever returns all three methods as high-scoring candidates so that
    # only the per-file cap determines how many from src/auth.py are selected.
    class _ThreeMethodRetriever:
        def retrieve(self, _repo_id, _snapshot_id, _query, _limit):
            items = [
                {"chunk_id": "setup", "file_path": "src/auth.py", "start_line": 10,
                 "end_line": 25, "chunk_type": "method", "content": setup_body, "score": 1.5},
                {"chunk_id": "merge", "file_path": "src/auth.py", "start_line": 30,
                 "end_line": 65, "chunk_type": "method", "content": merge_body, "score": 1.4},
                {"chunk_id": "send", "file_path": "src/auth.py", "start_line": 70,
                 "end_line": 110, "chunk_type": "method", "content": send_body, "score": 1.3},
            ]
            return type("Result", (), {"items": items, "run": type("Run", (), {"mode": "lexical"})()})()

    monkeypatch.setattr(mcp_tools, "HybridRetriever", _ThreeMethodRetriever)

    # With limit=6 all three methods in the same file must be returned.
    result6 = locate_code(
        repo_id,
        "where does a session merge proxy and certificate settings from the environment, "
        "and where that merged configuration is applied before dispatching the request",
        snapshot_id,
        limit=6,
    )
    starts6 = {item["start_line"] for item in result6["data"]["locations"]}
    assert 10 in starts6, "setup_environment must appear (limit=6)"
    assert 30 in starts6, "merge_environment_settings must appear (limit=6)"
    assert 70 in starts6, "send must appear (limit=6)"

    # With limit=4 the cap stays at 2 per file — diversity is preserved.
    result4 = locate_code(
        repo_id,
        "where does a session merge proxy and certificate settings from the environment, "
        "and where that merged configuration is applied before dispatching the request",
        snapshot_id,
        limit=4,
    )
    starts4 = {item["start_line"] for item in result4["data"]["locations"]}
    assert len([s for s in starts4 if s in {10, 30, 70}]) <= 2, "at most 2 from the same file when limit=4"


