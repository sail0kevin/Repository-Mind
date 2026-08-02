"""Channel-aware relevance decisions for retrieval evidence."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


RelevanceOutcome = Literal["accepted", "not_found", "low_relevance"]


@dataclass(frozen=True)
class RelevanceObservation:
    """Raw scores are retained in their original channel-specific spaces."""

    mode: str
    lexical_hit_count: int
    lexical_top_score: float | None
    lexical_top_exact_boost: float | None
    semantic_hit_count: int
    semantic_top_score: float | None
    rrf_top_score: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RelevanceDecision:
    accepted: bool
    outcome: RelevanceOutcome
    reason: str | None
    observation: RelevanceObservation

    def to_dict(self) -> dict:
        result = asdict(self)
        result["observation"] = self.observation.to_dict()
        return result


class RelevancePolicy:
    """Apply calibrated thresholds without comparing unlike score spaces.

    The defaults are intentionally conservative starter thresholds. The calibration
    runner records all observations so they can be updated from a reviewed negative
    set without changing the retrieval/fusion contracts.
    """

    def __init__(
        self,
        *,
        lexical_min_score: float = 1e-9,
        hybrid_lexical_min_score: float = 31.4,
        semantic_min_score: float = 0.51,
    ) -> None:
        self.lexical_min_score = max(0.0, float(lexical_min_score))
        self.hybrid_lexical_min_score = max(0.0, float(hybrid_lexical_min_score))
        self.semantic_min_score = max(-1.0, min(1.0, float(semantic_min_score)))

    @staticmethod
    def observe(mode: str, lexical_hits: list[dict], semantic_hits: list[dict]) -> RelevanceObservation:
        lexical_scores = [float(item.get("lexical_score", item.get("score", 0.0))) for item in lexical_hits]
        lexical_boosts = [float(item.get("exact_boost", 0.0)) for item in lexical_hits]
        semantic_scores = [float(item.get("semantic_score", item.get("vector_score", item.get("score", 0.0)))) for item in semantic_hits]
        return RelevanceObservation(
            mode=mode,
            lexical_hit_count=len(lexical_hits),
            lexical_top_score=max(lexical_scores, default=None),
            lexical_top_exact_boost=max(lexical_boosts, default=None),
            semantic_hit_count=len(semantic_hits),
            semantic_top_score=max(semantic_scores, default=None),
        )

    def decide(self, observation: RelevanceObservation) -> RelevanceDecision:
        if observation.lexical_hit_count == 0 and observation.semantic_hit_count == 0:
            return RelevanceDecision(False, "not_found", "no_channel_hits", observation)

        lexical_threshold = (
            self.hybrid_lexical_min_score if observation.mode == "hybrid" else self.lexical_min_score
        )
        lexical_accepted = bool(
            observation.lexical_hit_count
            and (
                (observation.lexical_top_exact_boost or 0.0) > 0.0
                or (observation.lexical_top_score or 0.0) >= lexical_threshold
            )
        )
        semantic_accepted = bool(
            observation.semantic_hit_count
            and (observation.semantic_top_score or -1.0) >= self.semantic_min_score
        )
        if lexical_accepted or semantic_accepted:
            return RelevanceDecision(True, "accepted", None, observation)

        reasons: list[str] = []
        if observation.lexical_hit_count:
            reasons.append("lexical_below_calibrated_threshold")
        if observation.semantic_hit_count:
            reasons.append("semantic_below_calibrated_threshold")
        return RelevanceDecision(False, "low_relevance", "+".join(reasons), observation)
