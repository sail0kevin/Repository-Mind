"""M4 Main Agent 条件路由、轨迹和无 Key 降级测试。"""
from pathlib import Path

from fastapi.testclient import TestClient

from service.core.agent.router import route_question
from service.core.qa import _fallback_answer
from service.main import create_app
from service.storage.repository_store import create_repo_record, replace_file_records
from service.storage.snapshot_store import get_or_create_snapshot, publish_snapshot
from service.storage.evidence_store import project_evidence_to_chunks, replace_snapshot_parse_results


def _seed(tmp_path: Path) -> tuple[str, str]:
    repo_id = create_repo_record(tmp_path, "agent-demo", current_commit="a" * 40)
    snapshot, _ = get_or_create_snapshot(repo_id, "a" * 40, "main")
    replace_file_records(repo_id, [{"relative_path": "src/auth.py", "language": "python", "file_type": "text",
                                    "is_binary": False, "is_test_file": False, "parse_status": "parsed"}],
                         snapshot_id=snapshot["id"])
    from service.storage.sqlite_db import get_connection
    with get_connection() as connection:
        file_id = connection.execute("SELECT id FROM files WHERE snapshot_id = ?", (snapshot["id"],)).fetchone()[0]
    evidence = {"id": "ev_auth", "logical_id": "evl_auth", "identity_key": "auth",
                "snapshot_id": snapshot["id"], "file_id": file_id, "unit_type": "function",
                "content": "def authenticate(token): return bool(token)", "parser_name": "test", "parser_version": "1"}
    symbol = {"id": "sym_auth", "logical_id": "syml_auth", "identity_key": "auth",
              "snapshot_id": snapshot["id"], "file_id": file_id, "evidence_id": "ev_auth",
              "qualified_name": "src.auth.authenticate", "name": "authenticate", "symbol_kind": "function"}
    replace_snapshot_parse_results(repo_id, snapshot["id"], file_id, [evidence], [symbol], [], [])
    project_evidence_to_chunks(repo_id, snapshot["id"])
    publish_snapshot(repo_id, snapshot["id"], "main", 1)
    return repo_id, snapshot["id"]


def test_router_simple_question_uses_zero_tools_and_specialized_questions_are_narrow():
    assert route_question("这个函数做什么").tools == ()
    assert route_question("GreetingService.build_message 方法是做什么的？").tools == ()
    assert [item.name for item in route_question("认证和密钥是否安全").tools] == ["security_review"]
    assert [item.name for item in route_question("修改 authenticate 会影响谁").tools] == ["dependency_impact"]
    assert len(route_question("测试失败怎么运行").tools) <= 2


def test_ask_persists_trace_and_no_key_fallback(tmp_path: Path):
    repo_id, snapshot_id = _seed(tmp_path)
    with TestClient(create_app()) as client:
        response = client.post(f"/api/v1/repos/{repo_id}/ask", json={"question": "authenticate 做什么", "limit": 5})
        assert response.status_code == 200
        payload = response.json()
        assert payload["snapshot_id"] == snapshot_id
        assert payload["trace_id"].startswith("trace_")
        assert payload["evidence"]
        assert all(item["file_path"] for item in payload["evidence"])
        trace = client.get(f"/api/v1/repos/{repo_id}/traces/{payload['trace_id']}")
    assert trace.status_code == 200
    body = trace.json()
    assert body["status"] == "fallback"
    assert [step["step_type"] for step in body["steps"]] == ["route", "retrieval", "synthesis"]
    assert body["session_id"]
    assert "api_key" not in trace.text.casefold()


def test_security_question_calls_only_security_tool(tmp_path: Path):
    repo_id, _ = _seed(tmp_path)
    with TestClient(create_app()) as client:
        response = client.post(f"/api/v1/repos/{repo_id}/ask", json={"question": "认证 token 是否有安全风险", "limit": 5})
        trace = client.get(f"/api/v1/repos/{repo_id}/traces/{response.json()['trace_id']}").json()
    tools = [step["tool_name"] for step in trace["steps"] if step["step_type"] == "tool"]
    assert tools == ["security_review"]


def test_rule_fallback_never_emits_empty_evidence_reference():
    result = _fallback_answer(
        "where is the entry point?",
        [{"file_path": None, "path": "src/main.py", "start_line": 3, "end_line": 4,
          "snippet": "def main(): ..."}],
        None,
    )
    assert "[1] :" not in result["answer"]
    assert "src/main.py:3-4" in result["answer"]


def test_missing_trace_returns_404(tmp_path: Path):
    repo_id, _ = _seed(tmp_path)
    with TestClient(create_app()) as client:
        response = client.get(f"/api/v1/repos/{repo_id}/traces/trace_does_not_exist")
    assert response.status_code == 404
