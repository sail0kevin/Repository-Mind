"""验证搜索和问答的 limit 契约，以及真实 embedding 上线前的词法检索标记。"""
from pathlib import Path

import pytest

from service.api.v1 import repos as repos_api
from service.core.vector_store import replace_repo_vector_index
from service.storage.chunk_store import replace_repo_chunks
from service.storage.models import QARequest, SearchRequest
from service.storage.repository_store import create_repo_record
from service.storage.snapshot_store import create_or_get_snapshot, finish_snapshot, set_active_snapshot


def _seed_searchable_repository(repo_path: Path, chunk_count: int = 6) -> str:
    """写入一组都含相同关键词的 chunk，便于精确验证结果上限。"""
    repo_id = create_repo_record(repo_path, alias="search-fixture")
    snapshot = create_or_get_snapshot(repo_id, "d" * 40)
    assert finish_snapshot(snapshot["id"], "succeeded")
    assert set_active_snapshot(repo_id, snapshot["id"])
    replace_repo_chunks(
        repo_id,
        {
            "src/search.py": [
                {
                    "file_path": f"src/module_{index}.py",
                    "chunk_type": "python",
                    "title": f"module_{index}",
                    "start_line": index + 1,
                    "end_line": index + 1,
                    "content": f"needle needle module {index}",
                    "content_hash": f"hash-{index}",
                    "source_type": "text",
                }
                for index in range(chunk_count)
            ]
        },
    )
    return repo_id


def test_search_limit_is_applied_and_results_are_lexical(tmp_path: Path) -> None:
    """search 请求的 limit 必须控制最终证据数量，词法命中不能误标成语义匹配。"""
    repo_id = _seed_searchable_repository(tmp_path)

    response = repos_api.search_repository(repo_id, SearchRequest(query="needle", limit=2))

    assert len(response.evidence) == 2
    assert all(item.reason == "文本匹配" for item in response.evidence)
    assert all(item.score > 0 for item in response.evidence)
    assert all(item.snippet for item in response.evidence)


def test_placeholder_vectors_do_not_hide_lexical_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """占位向量没有 chunk 和数值 embedding，检索流程必须继续使用完整词法结果。"""
    repo_id = _seed_searchable_repository(tmp_path)
    replace_repo_vector_index(
        repo_id,
        [{"id": "placeholder", "chunk_id": None, "embedding": None}],
    )

    def fail_if_semantic_search_runs(*args, **kwargs):
        raise AssertionError("没有真实 embedding 时不应调用语义检索")

    monkeypatch.setattr(repos_api, "search_vectors", fail_if_semantic_search_runs)
    response = repos_api.search_repository(repo_id, SearchRequest(query="needle", limit=3))

    assert len(response.evidence) == 3
    assert {item.reason for item in response.evidence} == {"文本匹配"}
    assert all(item.chunk_id for item in response.evidence)


def test_ask_limit_controls_evidence_and_llm_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ask 的 limit 同时约束返回证据和传给回答生成器的上下文。"""
    repo_id = _seed_searchable_repository(tmp_path)
    captured: dict = {}

    def fake_main_agent(context):
        from service.core.agent.models import MainAgentResult
        evidence, _ = repos_api._qa_evidence(
            context.repo_id, context.question, context.limit, context.snapshot_id, context.commit
        )
        captured["question"] = context.question
        captured["evidence"] = [item.model_dump() for item in evidence]
        return MainAgentResult(
            answer="本地测试回答", evidence=captured["evidence"], confidence="low",
            used_context=len(evidence), trace_id="trace_test", next_steps=[], token_count=0,
            generation_mode="rule_fallback",
        )

    monkeypatch.setattr(repos_api, "run_main_agent", fake_main_agent)
    monkeypatch.setattr(repos_api, "create_session_record", lambda *args: "session_test")
    monkeypatch.setattr(repos_api, "bind_trace_session", lambda *_args: None)

    response = repos_api.ask_repository(repo_id, QARequest(question="needle", limit=1))

    assert len(response.evidence) == 1
    assert len(captured["evidence"]) == 1
    assert response.used_context == 1
    assert response.evidence[0].reason == "文本匹配"
