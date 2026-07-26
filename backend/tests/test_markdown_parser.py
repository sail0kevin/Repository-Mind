"""Markdown parser identity regression tests."""
from __future__ import annotations

from service.core.parsing.markdown_adapter import parse_markdown


def test_repeated_heading_titles_produce_distinct_evidence_identities() -> None:
    """Repeated display headings must not make a snapshot fail its unique Evidence constraint."""
    result = parse_markdown(
        "# Plan\n\nFirst section.\n\n# Plan\n\nSecond section.\n",
        snapshot_id="snapshot-markdown-duplicate-heading",
        file_path="docs/plan.md",
    )

    sections = [item for item in result.evidence if item.kind == "section"]
    assert [item.title for item in sections] == ["Plan", "Plan"]
    assert len({item.logical_id for item in sections}) == 2
    assert len({item.id for item in sections}) == 2
