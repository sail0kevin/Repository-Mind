"""M3 HybridRetriever 与 EvidenceAssembler 的确定性契约测试。"""
from __future__ import annotations

from service.core.evidence import EvidenceAssembler, EvidenceBudget
from service.core.retrieval.fusion import ReciprocalRankFusion
from service.core.retrieval.planner import RetrievalPlanner
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


class FakeStructural:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def expand(self, repo_id: str, snapshot_id: str, seeds: list[dict], limit: int) -> list[dict]:
        return [dict(item) for item in self.rows[:limit]]


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
