from service.core.retrieval.relevance import RelevancePolicy
from service.storage.lexical_store import _fts_match_expression, normalize_query


def test_no_channel_hits_is_not_found() -> None:
    policy = RelevancePolicy()

    decision = policy.decide(policy.observe("lexical", [], []))

    assert not decision.accepted
    assert decision.outcome == "not_found"
    assert decision.reason == "no_channel_hits"


def test_exact_or_positive_lexical_hit_is_accepted_without_semantic_score() -> None:
    policy = RelevancePolicy()
    lexical = [{"lexical_score": 0.00001, "exact_boost": 4.0, "score": 4.00001}]

    decision = policy.decide(policy.observe("hybrid", lexical, [{"semantic_score": 0.01}]))

    assert decision.accepted
    assert decision.outcome == "accepted"
    assert decision.observation.lexical_top_score == 0.00001
    assert decision.observation.semantic_top_score == 0.01


def test_semantic_threshold_only_applies_to_semantic_channel() -> None:
    policy = RelevancePolicy(lexical_min_score=0.1, hybrid_lexical_min_score=0.1, semantic_min_score=0.2)

    decision = policy.decide(policy.observe("hybrid", [{"lexical_score": 0.05}], [{"semantic_score": 0.21}]))

    assert decision.accepted
    assert decision.outcome == "accepted"


def test_low_channel_scores_are_rejected_deterministically() -> None:
    policy = RelevancePolicy(lexical_min_score=0.1, hybrid_lexical_min_score=0.1, semantic_min_score=0.2)

    decision = policy.decide(policy.observe("hybrid", [{"lexical_score": 0.099}], [{"semantic_score": 0.199}]))

    assert not decision.accepted
    assert decision.outcome == "low_relevance"
    assert decision.reason == "lexical_below_calibrated_threshold+semantic_below_calibrated_threshold"


def test_rrf_score_is_observed_but_never_used_as_confidence_threshold() -> None:
    policy = RelevancePolicy(lexical_min_score=0.1, hybrid_lexical_min_score=0.1, semantic_min_score=0.2)
    observation = policy.observe("hybrid", [{"lexical_score": 0.101}], [])
    observation = type(observation)(**{**observation.to_dict(), "rrf_top_score": 0.0001})

    decision = policy.decide(observation)

    assert decision.accepted
    assert decision.observation.rrf_top_score == 0.0001


def test_hybrid_lexical_threshold_rejects_incidental_text_match() -> None:
    policy = RelevancePolicy(
        lexical_min_score=0.1,
        hybrid_lexical_min_score=31.4,
        semantic_min_score=0.51,
    )

    decision = policy.decide(policy.observe(
        "hybrid",
        [{"lexical_score": 31.360885187333867, "exact_boost": 0.0}],
        [{"semantic_score": 0.4446070574613917}],
    ))

    assert not decision.accepted
    assert decision.reason == "lexical_below_calibrated_threshold+semantic_below_calibrated_threshold"


def test_lexical_mode_preserves_recall_oriented_threshold() -> None:
    policy = RelevancePolicy(
        lexical_min_score=1e-9,
        hybrid_lexical_min_score=31.4,
        semantic_min_score=0.51,
    )

    decision = policy.decide(policy.observe("lexical", [{"lexical_score": 0.00001}], []))

    assert decision.accepted


def test_unrelated_english_domain_question_requires_four_meaningful_terms() -> None:
    query = "How does a Kubernetes Helm blue green rollout manage release traffic?"

    expression = _fts_match_expression(query, normalize_query(query))

    assert '("kubernetes" AND "helm" AND "blue" AND "green")' in expression
    assert '("kubernetes" AND "helm" AND "blue")' not in expression
