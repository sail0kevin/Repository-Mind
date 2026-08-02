"""M4 Main Agent 条件路由、轨迹和无 Key 降级测试。"""
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from service.core.agent import tools as agent_tools
from service.core.agent.models import AgentContext
from service.core.agent import main_agent
from service.core.agent.main_agent import _merge_tool_evidence
from service.core.agent.router import route_question
from service.core.agent.tools import _symbol_term, dependency_impact
from service.core.qa import _fallback_answer
from service.core.debate import AgentContribution, DebateResult
from service.main import create_app
from service.storage.repository_store import create_repo_record, replace_file_records
from service.storage.snapshot_store import get_or_create_snapshot, publish_snapshot
from service.storage.evidence_store import project_evidence_to_chunks, replace_snapshot_parse_results


def _seed(tmp_path: Path, *, second_source: bool = False) -> tuple[str, str]:
    repo_id = create_repo_record(tmp_path, "agent-demo", current_commit="a" * 40)
    snapshot, _ = get_or_create_snapshot(repo_id, "a" * 40, "main")
    files = [{"relative_path": "src/auth.py", "language": "python", "file_type": "text",
              "is_binary": False, "is_test_file": False, "parse_status": "parsed"}]
    if second_source:
        files.append({"relative_path": "docs/architecture.md", "language": "markdown", "file_type": "text",
                      "is_binary": False, "is_test_file": False, "parse_status": "parsed"})
    replace_file_records(repo_id, files,
                         snapshot_id=snapshot["id"])
    from service.storage.sqlite_db import get_connection
    with get_connection() as connection:
        file_ids = {
            row["relative_path"]: row["id"]
            for row in connection.execute("SELECT id, relative_path FROM files WHERE snapshot_id = ?", (snapshot["id"],))
        }
    file_id = file_ids["src/auth.py"]
    evidence = {"id": "ev_auth", "logical_id": "evl_auth", "identity_key": "auth",
                "snapshot_id": snapshot["id"], "file_id": file_id, "unit_type": "function",
                "content": "def authenticate(token): return bool(token)", "parser_name": "test", "parser_version": "1"}
    symbol = {"id": "sym_auth", "logical_id": "syml_auth", "identity_key": "auth",
              "snapshot_id": snapshot["id"], "file_id": file_id, "evidence_id": "ev_auth",
              "qualified_name": "src.auth.authenticate", "name": "authenticate", "symbol_kind": "function"}
    replace_snapshot_parse_results(repo_id, snapshot["id"], file_id, [evidence], [symbol], [], [])
    if second_source:
        architecture_file_id = file_ids["docs/architecture.md"]
        architecture_evidence = {
            "id": "ev_architecture", "logical_id": "evl_architecture", "identity_key": "architecture",
            "snapshot_id": snapshot["id"], "file_id": architecture_file_id, "unit_type": "section",
            "content": "Architecture design documents the service boundaries and evolution tradeoffs.",
            "parser_name": "test", "parser_version": "1",
        }
        replace_snapshot_parse_results(repo_id, snapshot["id"], architecture_file_id,
                                       [architecture_evidence], [], [], [])
    project_evidence_to_chunks(repo_id, snapshot["id"])
    publish_snapshot(repo_id, snapshot["id"], "main", 1)
    return repo_id, snapshot["id"]


def test_router_simple_question_uses_zero_tools_and_specialized_questions_are_narrow():
    assert route_question("这个函数做什么").tools == ()
    assert route_question("GreetingService.build_message 方法是做什么的？").tools == ()
    assert [item.name for item in route_question("认证和密钥是否安全").tools] == ["security_review"]
    assert [item.name for item in route_question("修改 authenticate 会影响谁").tools] == ["dependency_impact"]
    assert len(route_question("测试失败怎么运行").tools) <= 2


def test_router_only_selects_debate_for_complex_non_symbol_questions():
    complex_plan = route_question("Why was this architecture designed this way, and what tradeoffs should guide its future evolution?")
    assert complex_plan.debate_roles == ("developer", "architect")
    assert complex_plan.debate_reason == "complex_open_question"

    exact_symbol_plan = route_question("Why does GreetingService.build_message use this architecture?")
    assert exact_symbol_plan.debate_roles == ()
    assert exact_symbol_plan.debate_reason == "precise_symbol_query"


def test_specialist_term_extraction_prefers_symbol_over_question_tail() -> None:
    assert _symbol_term("Changing GreetingService.build_message impact call chain and tests") == "GreetingService.build_message"
    assert _symbol_term("修改 authenticate 会影响哪些调用方") == "authenticate"


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
    assert [step["step_type"] for step in body["steps"]] == ["route", "retrieval", "debate", "synthesis"]
    debate = body["steps"][2]
    assert debate["status"] == "skipped"
    assert debate["output_summary"]["reason"] == "not_complex_enough"
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


def test_ask_with_no_retrieval_hits_returns_explicit_insufficient_evidence(tmp_path: Path):
    repo_id, _ = _seed(tmp_path)
    with TestClient(create_app()) as client:
        response = client.post(
            f"/api/v1/repos/{repo_id}/ask",
            json={"question": "Kubernetes Helm rollout blue green migration", "limit": 5},
        )
        payload = response.json()
        trace = client.get(f"/api/v1/repos/{repo_id}/traces/{payload['trace_id']}").json()

    assert response.status_code == 200
    assert payload["confidence"] == "insufficient_evidence"
    assert payload["evidence"] == []
    assert "相关代码证据" in payload["answer"]
    retrieval = next(step for step in trace["steps"] if step["step_type"] == "retrieval")
    assert retrieval["output_summary"]["relevance"]["outcome"] == "not_found"


def test_complex_question_with_single_source_evidence_skips_debate(tmp_path: Path):
    repo_id, _ = _seed(tmp_path)
    question = "Why was this architecture designed this way, and what tradeoffs should guide its future evolution?"
    with TestClient(create_app()) as client:
        response = client.post(f"/api/v1/repos/{repo_id}/ask", json={"question": question, "limit": 5})
        trace = client.get(f"/api/v1/repos/{repo_id}/traces/{response.json()['trace_id']}").json()

    debate_steps = [step for step in trace["steps"] if step["step_type"] == "debate"]
    assert response.status_code == 200
    assert len(debate_steps) == 1
    assert debate_steps[0]["status"] == "skipped"
    assert debate_steps[0]["output_summary"]["reason"] == "insufficient_grounded_evidence"


def test_complex_question_uses_grounded_debate_instead_of_normal_synthesis(tmp_path: Path, monkeypatch):
    repo_id, snapshot_id = _seed(tmp_path, second_source=True)
    question = "Why was this architecture design chosen, and what tradeoffs should guide its future evolution?"
    calls: list[dict] = []

    def fake_debate(_self, *, topic, context, agents):
        calls.append({"topic": topic, "context": context, "agents": agents})
        return DebateResult(
            topic=topic,
            contributions=[
                AgentContribution("Developer", "developer", "Developer view [1]", True),
                AgentContribution("Architect", "architect", "Architect view [1]", True),
            ],
            summary="Developer view [1]\n\nArchitect view [1]",
            total_tokens_used=42,
            agents_used_llm=2,
        )

    def unexpected_synthesis(*_args, **_kwargs):
        raise AssertionError("normal synthesis must not run after a successful debate")

    class GroundedRetriever:
        def retrieve(self, *_args, **_kwargs):
            return SimpleNamespace(
                items=[
                    {"chunk_id": "ev_auth", "file_path": "src/auth.py", "start_line": 1, "end_line": 1,
                     "content": "def authenticate(token): return bool(token)", "score": 1.0},
                    {"chunk_id": "ev_architecture", "file_path": "docs/architecture.md", "start_line": 1, "end_line": 1,
                     "content": "Architecture design documents service boundaries and evolution tradeoffs.", "score": 0.9},
                ],
                run=SimpleNamespace(mode="lexical", relevance=None, events=[]),
            )

    monkeypatch.setattr(main_agent.MultiAgentDebateService, "run_debate", fake_debate)
    monkeypatch.setattr(main_agent, "answer_question", unexpected_synthesis)
    monkeypatch.setattr(main_agent, "HybridRetriever", GroundedRetriever)
    result = main_agent.run_main_agent(AgentContext(
        repo_id=repo_id,
        snapshot_id=snapshot_id,
        commit="a" * 40,
        question=question,
        limit=5,
    ))

    assert result.generation_mode == "llm_debate"
    assert result.token_count == 42
    assert "Developer view" in result.answer
    assert [agent["role"] for agent in calls[0]["agents"]] == ["developer", "architect"]
    assert all(chunk["file_path"] for chunk in calls[0]["context"]["chunks"])


def test_specialist_tool_evidence_is_merged_into_synthesis_context() -> None:
    existing = [{"chunk_id": "retrieval-1", "file_path": "README.md", "start_line": 1, "end_line": 2}]
    additions = [
        {"chunk_id": "tool-1", "file_path": "src/service.py", "start_line": 10, "end_line": 20,
         "content": "def build_message(): ..."},
        {"chunk_id": "tool-1", "file_path": "src/service.py", "start_line": 10, "end_line": 20,
         "content": "def build_message(): ..."},
        {"chunk_id": "", "file_path": "   ", "start_line": None, "end_line": None,
         "content": "not referenceable"},
    ]

    merged = _merge_tool_evidence(existing, additions)

    assert [item["file_path"] for item in merged] == ["README.md", "src/service.py"]


def test_missing_trace_returns_404(tmp_path: Path):
    repo_id, _ = _seed(tmp_path)
    with TestClient(create_app()) as client:
        response = client.get(f"/api/v1/repos/{repo_id}/traces/trace_does_not_exist")
    assert response.status_code == 404
