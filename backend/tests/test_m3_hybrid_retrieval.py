"""M3 HybridRetriever 与 EvidenceAssembler 的确定性契约测试。"""
from __future__ import annotations

from service.core.evidence import EvidenceAssembler, EvidenceBudget
from service.core.retrieval.fusion import ReciprocalRankFusion
from service.core.retrieval.planner import RetrievalPlanner
from service.core.retrieval.relevance import RelevancePolicy
from service.core.retrieval.semantic import SemanticRetriever
from service.core.retrieval.service import HybridRetriever


class FakeRetriever:
    def __init__(self, name: str, rows: list[dict], available: bool = True) -> None:
        self.name = name
        self.rows = rows
        self._available = available

    def available(self, repo_id: str, snapshot_id: str) -> bool:
        return self._available

    def retrieve(self, repo_id: str, snapshot_id: str, query: str, limit: int) -> list[dict]:
        results = []
        for rank, row in enumerate(self.rows[:limit], start=1):
            item = dict(row)
            item.setdefault("retriever", self.name)
            item.setdefault("rank", rank)
            item.setdefault("signals", [self.name])
            results.append(item)
        return results


class QueryUnavailableSemanticRetriever(FakeRetriever):
    def retrieve_with_status(
        self, repo_id: str, snapshot_id: str, query: str, limit: int
    ) -> tuple[list[dict], bool]:
        return [], False


class FakeStructural:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def expand(self, repo_id: str, snapshot_id: str, seeds: list[dict], limit: int) -> list[dict]:
        return [dict(item) for item in self.rows[:limit]]


class FakeReranker:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str], int]] = []

    def available(self) -> bool:
        return True

    def rerank(self, query: str, candidates: list[dict], limit: int) -> list[dict]:
        self.calls.append((query, [item["chunk_id"] for item in candidates], limit))
        return list(reversed(candidates))


def _candidate(chunk_id: str, path: str, content: str, score: float = 1.0) -> dict:
    return {
        "id": chunk_id,
        "chunk_id": chunk_id,
        "file_path": path,
        "start_line": 1,
        "end_line": 3,
        "content": content,
        "score": score,
        "source_type": "function",
    }


def test_rrf_is_deterministic_and_deduplicates() -> None:
    lexical = [_candidate("a", "a.py", "alpha"), _candidate("b", "b.py", "beta")]
    semantic = [_candidate("b", "b.py", "beta"), _candidate("a", "a.py", "alpha")]
    fusion = ReciprocalRankFusion(k=60)

    first = fusion.fuse([lexical, semantic])
    second = fusion.fuse([lexical, semantic])

    assert [(item["chunk_id"], item["score"]) for item in first] == [
        (item["chunk_id"], item["score"]) for item in second
    ]
    assert [item["chunk_id"] for item in first] == ["a", "b"]
    assert first[0]["signals"] == ["channel_0", "channel_1"]


def test_hybrid_retriever_audits_channels_and_appends_one_hop() -> None:
    lexical = FakeRetriever("lexical", [_candidate("a", "a.py", "alpha"), _candidate("b", "b.py", "beta")])
    semantic = FakeRetriever("semantic", [_candidate("b", "b.py", "beta"), _candidate("c", "c.py", "gamma")])
    structural = FakeStructural([
        {**_candidate("d", "d.py", "delta", 0.0), "signals": ["structural"], "reason": "一跳结构扩展", "relation_path": ["a", "rel", "d"]}
    ])
    retriever = HybridRetriever(
        planner=RetrievalPlanner(candidate_multiplier=2), lexical=lexical, semantic=semantic,
        fusion=ReciprocalRankFusion(), structural=structural,
    )

    result = retriever.retrieve("repo", "snapshot", "query", limit=3)

    assert result.run.mode == "hybrid"
    assert result.run.channels == {"lexical": 2, "semantic": 2}
    assert result.run.events[2]["llm_reranker"] is False
    assert [item["chunk_id"] for item in result.items] == ["b", "a", "c", "d"]
    assert result.items[-1]["relation_path"] == ["a", "rel", "d"]
    assert result.run.relevance is not None
    assert result.run.relevance.accepted
    assert result.run.relevance.observation.lexical_top_score == 1.0
    assert result.run.relevance.observation.semantic_top_score == 1.0
    assert result.run.events[-1]["stage"] == "relevance"


def test_hybrid_retriever_suppresses_low_relevance_before_evidence_assembly() -> None:
    lexical = FakeRetriever("lexical", [_candidate("a", "a.py", "alpha", 0.05)])
    retriever = HybridRetriever(
        planner=RetrievalPlanner(), lexical=lexical, semantic=FakeRetriever("semantic", [], available=False),
        structural=FakeStructural([]), relevance=RelevancePolicy(lexical_min_score=0.1),
    )

    result = retriever.retrieve("repo", "snapshot", "unrelated", limit=3)

    assert result.items == []
    assert result.run.relevance is not None
    assert result.run.relevance.outcome == "low_relevance"
    assert result.run.events[-1]["stage"] == "relevance"


def test_hybrid_retriever_reports_lexical_when_query_embedding_is_unavailable() -> None:
    lexical = FakeRetriever("lexical", [_candidate("a", "a.py", "alpha")])
    semantic = QueryUnavailableSemanticRetriever("semantic", [], available=True)
    reranker = FakeReranker()
    retriever = HybridRetriever(
        lexical=lexical, semantic=semantic, structural=FakeStructural([]), reranker=reranker,
    )

    result = retriever.retrieve("repo", "snapshot", "query", limit=5)

    assert result.run.mode == "lexical"
    assert result.run.channels == {"lexical": 1}
    assert result.run.relevance is not None
    assert result.run.relevance.observation.mode == "lexical"
    assert reranker.calls == []
    assert result.run.events[1] == {
        "stage": "semantic_degraded",
        "reason": "query_embedding_unavailable",
        "planned_mode": "hybrid",
        "effective_mode": "lexical",
    }


def test_hybrid_retriever_skips_query_embedding_when_provider_is_unconfigured() -> None:
    lexical = FakeRetriever("lexical", [_candidate("a", "a.py", "alpha")])
    calls: list[str] = []
    semantic = SemanticRetriever(
        query_embedder=lambda query: calls.append(query) or [1.0, 0.5],
        availability=lambda *_args: True,
        query_configuration=lambda: type("Status", (), {
            "available": False,
            "reason": "embedding_provider_unconfigured",
        })(),
    )
    retriever = HybridRetriever(lexical=lexical, semantic=semantic, structural=FakeStructural([]))

    result = retriever.retrieve("repo", "snapshot", "query", limit=5)

    assert calls == []
    assert result.run.mode == "lexical"
    assert result.run.events[1] == {
        "stage": "semantic_degraded",
        "reason": "embedding_provider_unconfigured",
        "planned_mode": "hybrid",
        "effective_mode": "lexical",
    }


def test_reranker_is_limited_to_enabled_hybrid_queries_with_limit_at_least_five() -> None:
    lexical = FakeRetriever("lexical", [_candidate("a", "a.py", "alpha"), _candidate("b", "b.py", "beta")])
    semantic = FakeRetriever("semantic", [_candidate("c", "c.py", "gamma")])
    reranker = FakeReranker()
    retriever = HybridRetriever(
        lexical=lexical, semantic=semantic, structural=FakeStructural([]), reranker=reranker,
    )

    result = retriever.retrieve("repo", "snapshot", "query", limit=5)

    assert reranker.calls == [("query", ["a", "c", "b"], 3)]
    assert [item["chunk_id"] for item in result.items[:3]] == ["b", "c", "a"]
    assert result.run.events[3] == {"stage": "rerank", "applied": True, "candidate_count": 3}

    retriever.retrieve("repo", "snapshot", "query", limit=4)
    assert len(reranker.calls) == 1


def test_reranker_candidate_limit_caps_only_the_reranked_head() -> None:
    lexical = FakeRetriever("lexical", [
        _candidate("a", "a.py", "alpha"),
        _candidate("b", "b.py", "beta"),
        _candidate("c", "c.py", "gamma"),
    ])
    semantic = FakeRetriever("semantic", [
        _candidate("d", "d.py", "delta"),
        _candidate("e", "e.py", "epsilon"),
        _candidate("f", "f.py", "zeta"),
    ])
    reranker = FakeReranker()
    retriever = HybridRetriever(
        lexical=lexical,
        semantic=semantic,
        structural=FakeStructural([]),
        reranker=reranker,
        reranker_candidate_limit=5,
    )

    result = retriever.retrieve("repo", "snapshot", "query", limit=5)

    assert reranker.calls == [("query", ["a", "d", "b", "e", "c"], 5)]
    assert [item["chunk_id"] for item in result.items] == ["c", "e", "b", "d", "a"]
    assert result.run.events[3] == {"stage": "rerank", "applied": True, "candidate_count": 5}


def test_evidence_assembler_enforces_token_file_and_source_budgets() -> None:
    candidates = [
        _candidate("a1", "a.py", "alpha " * 30, 3.0),
        _candidate("a2", "a.py", "alpha2 " * 30, 2.0),
        _candidate("b1", "b.py", "beta " * 30, 1.0),
    ]
    assembler = EvidenceAssembler(EvidenceBudget(
        total_tokens=30, max_file_ratio=0.5, max_evidence_tokens=12, min_sources=2, max_items=3,
    ))

    bundle = assembler.assemble(candidates, commit="f" * 40)

    assert bundle.total_tokens <= 30
    assert bundle.source_count == 2
    assert all(item.token_count <= 12 for item in bundle.items)
    assert sum(item.token_count for item in bundle.items if item.path == "a.py") <= 15
    assert {item.path for item in bundle.items} == {"a.py", "b.py"}
    assert all(item.commit == "f" * 40 for item in bundle.items)
