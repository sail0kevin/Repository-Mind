"""Optional second-stage reranking with a disabled-by-default local provider."""
from __future__ import annotations

from typing import Protocol

from service.storage.settings_store import get_setting


DEFAULT_RERANKER_CANDIDATE_LIMIT = 50
MIN_RERANKER_CANDIDATE_LIMIT = 5


def get_reranker_candidate_limit() -> int:
    """Read a bounded candidate cap without letting malformed local settings break search."""
    value = get_setting("reranker_candidate_limit", DEFAULT_RERANKER_CANDIDATE_LIMIT)
    try:
        return min(DEFAULT_RERANKER_CANDIDATE_LIMIT, max(MIN_RERANKER_CANDIDATE_LIMIT, int(value)))
    except (TypeError, ValueError):
        return DEFAULT_RERANKER_CANDIDATE_LIMIT


class CandidateReranker(Protocol):
    """A provider that returns the supplied candidates in reranked order."""

    def available(self) -> bool: ...

    def rerank(self, query: str, candidates: list[dict], limit: int) -> list[dict]: ...


class DisabledReranker:
    """Keep the baseline retrieval order when no local model is configured."""

    def available(self) -> bool:
        return False

    def rerank(self, query: str, candidates: list[dict], limit: int) -> list[dict]:
        return list(candidates)


class FlagEmbeddingReranker:
    """Lazy BGE reranker; importing or loading it never affects baseline retrieval."""

    def __init__(self, model: str, use_fp16: bool) -> None:
        self.model = model
        self.use_fp16 = use_fp16
        self._model = None
        self._unavailable = False

    def available(self) -> bool:
        if self._unavailable:
            return False
        try:
            self._load()
        except (ImportError, OSError, RuntimeError, ValueError):
            self._unavailable = True
        return not self._unavailable

    def rerank(self, query: str, candidates: list[dict], limit: int) -> list[dict]:
        if not self.available() or not candidates:
            return list(candidates)
        pairs = [(query, str(item.get("content") or "")) for item in candidates]
        scores = self._model.compute_score(pairs)
        if not isinstance(scores, list):
            scores = [scores]
        scored = [
            (dict(item, reranker_score=float(score)), index)
            for index, (item, score) in enumerate(zip(candidates, scores))
        ]
        scored.sort(key=lambda row: (-row[0]["reranker_score"], row[1]))
        return [item for item, _ in scored[:limit]]

    def _load(self) -> None:
        if self._model is not None:
            return
        from FlagEmbedding import FlagReranker

        self._model = FlagReranker(self.model, use_fp16=self.use_fp16)


def resolve_reranker() -> CandidateReranker:
    """Read non-sensitive reranker settings without making it a hard dependency."""
    provider = str(get_setting("reranker_provider", "disabled") or "disabled").strip().lower()
    if provider != "flag_embedding":
        return DisabledReranker()
    return FlagEmbeddingReranker(
        str(get_setting("reranker_model", "BAAI/bge-reranker-v2-m3") or "BAAI/bge-reranker-v2-m3"),
        bool(get_setting("reranker_use_fp16", False)),
    )
