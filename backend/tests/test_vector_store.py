"""P1-1 vector-search correctness contracts."""
from __future__ import annotations

from array import array

from service.core.vector_store import _cosine_similarity, _rank_vector_rows


def _row(vector: list[float], dimension: int | None = None) -> dict:
    values = array("f", vector)
    return {"vector": values.tobytes(), "dimension": dimension if dimension is not None else len(vector)}


def test_vector_ranking_matches_python_cosine_order_and_scores() -> None:
    query = [1.0, 0.0, 0.0]
    rows = [_row([0.5, 0.0, 0.0]), _row([0.0, 1.0, 0.0]), _row([0.75, 0.25, 0.0])]

    ranked = _rank_vector_rows(rows, query, limit=8)

    expected = [
        (index, _cosine_similarity(query, list(array("f", row["vector"]))))
        for index, row in enumerate(rows)
    ]
    expected = [(index, score) for index, score in expected if score > 0]
    expected.sort(key=lambda item: item[1], reverse=True)
    assert [index for index, _score in ranked] == [index for index, _score in expected]
    assert [score for _index, score in ranked] == [score for _index, score in expected]


def test_vector_ranking_keeps_input_order_for_equal_scores() -> None:
    rows = [_row([1.0, 0.0]), _row([2.0, 0.0]), _row([-1.0, 0.0])]

    ranked = _rank_vector_rows(rows, [1.0, 0.0], limit=8)

    assert [index for index, _score in ranked] == [0, 1]


def test_vector_ranking_ignores_zero_query_and_incompatible_rows() -> None:
    rows = [_row([1.0, 0.0]), _row([1.0], dimension=1), _row([1.0, 0.0], dimension=3)]

    assert _rank_vector_rows(rows, [0.0, 0.0], limit=8) == []
    assert _rank_vector_rows(rows, [1.0, 0.0], limit=8) == [(0, 1.0)]
