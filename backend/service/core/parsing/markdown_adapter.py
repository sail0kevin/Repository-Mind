"""Markdown ParserAdapter：提取标题树和自然段证据。"""
from __future__ import annotations

import re
from dataclasses import replace

from service.core.parsing.base import ParserAdapter
from service.core.parsing.models import EvidenceUnit, ParseResult, Relation, SourceDocument, Symbol

_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+|$)(.*?)[ \t]*#*[ \t]*$")
_SETEXT = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


class MarkdownParser(ParserAdapter):
    """按标题层级和自然段解析 Markdown。"""

    languages = frozenset({"markdown", "md"})
    extensions = frozenset({".md", ".markdown"})

    def __init__(self, max_chars: int = 1500) -> None:
        self.max_chars = max_chars

    def parse(self, document: SourceDocument) -> ParseResult:
        result = ParseResult(document=document)
        lines = document.content.splitlines()
        headings: list[tuple[int, str, int, int]] = []
        fence: str | None = None
        index = 0
        while index < len(lines):
            marker = _FENCE.match(lines[index])
            if marker:
                char = marker.group(1)[0]
                fence = None if fence == char else (char if fence is None else fence)
                index += 1
                continue
            if fence:
                index += 1
                continue
            match = _HEADING.match(lines[index])
            if match:
                headings.append((len(match.group(1)), match.group(2).strip(), index, index))
            elif index + 1 < len(lines) and lines[index].strip() and (under := _SETEXT.match(lines[index + 1])):
                headings.append((1 if under.group(1).startswith("=") else 2, lines[index].strip(), index, index + 1))
                index += 1
            index += 1

        stack: list[tuple[int, Symbol, EvidenceUnit]] = []
        heading_by_start: dict[int, tuple[Symbol, EvidenceUnit]] = {}
        counts: dict[str, int] = {}
        for level, title, start, end in headings:
            while stack and stack[-1][0] >= level:
                stack.pop()
            parent_symbol = stack[-1][1] if stack else None
            parent_evidence = stack[-1][2] if stack else None
            base = f"{parent_symbol.qualified_name}/{title}" if parent_symbol else title
            counts[base] = counts.get(base, 0) + 1
            qualified = base if counts[base] == 1 else f"{base}[{counts[base]}]"
            symbol = Symbol.create(document, name=title, qualified_name=qualified, kind="section",
                                   start_line=start + 1, end_line=end + 1,
                                   parent_id=parent_symbol.id if parent_symbol else None,
                                   metadata={"level": level})
            evidence = EvidenceUnit.create(document, start + 1, end + 1, kind="section",
                                           content="\n".join(lines[start:end + 1]), symbol_id=symbol.id,
                                           parent_id=parent_evidence.id if parent_evidence else None,
                                           title=title, metadata={"level": level, "heading_path": qualified})
            symbol = replace(symbol, evidence_id=evidence.id)
            result.symbols.append(symbol)
            result.evidence.append(evidence)
            heading_by_start[start] = (symbol, evidence)
            if parent_symbol:
                result.relations.append(Relation.create(document, kind="contains", source_id=parent_symbol.id,
                    target_id=symbol.id, target_ref=qualified, observed=True, inferred=False, confidence=1.0,
                    evidence_id=evidence.id, line=start + 1))
            stack.append((level, symbol, evidence))

        boundaries = headings + [(0, "", len(lines), len(lines))]
        previous = 0
        active: tuple[Symbol, EvidenceUnit] | None = None
        for _, _, start, end in boundaries:
            self._paragraphs(document, result, lines, previous, start, active)
            if start < len(lines):
                active = heading_by_start[start]
                previous = end + 1
        result.sort_facts()
        return result

    def _paragraphs(self, document: SourceDocument, result: ParseResult, lines: list[str], start: int, end: int,
                    active: tuple[Symbol, EvidenceUnit] | None) -> None:
        cursor, part = start, 0
        while cursor < end:
            while cursor < end and not lines[cursor].strip(): cursor += 1
            paragraph_start = cursor
            while cursor < end and lines[cursor].strip(): cursor += 1
            if paragraph_start == cursor: continue
            current: list[str] = []
            chunk_start = paragraph_start
            for line_index in range(paragraph_start, cursor):
                line = lines[line_index]
                if current and len("\n".join([*current, line])) > self.max_chars:
                    part += 1
                    self._add_paragraph(document, result, current, chunk_start, line_index - 1, active, part)
                    current, chunk_start = [line], line_index
                else: current.append(line)
            if current:
                part += 1
                self._add_paragraph(document, result, current, chunk_start, cursor - 1, active, part)

    @staticmethod
    def _add_paragraph(document: SourceDocument, result: ParseResult, lines: list[str], start: int, end: int,
                       active: tuple[Symbol, EvidenceUnit] | None, part: int) -> None:
        parent_symbol, parent_evidence = active if active else (None, None)
        evidence = EvidenceUnit.create(document, start + 1, end + 1, kind="paragraph", content="\n".join(lines),
            parent_id=parent_evidence.id if parent_evidence else None,
            title=parent_evidence.title if parent_evidence else None, metadata={"part": part})
        result.evidence.append(evidence)
        if parent_symbol:
            result.relations.append(Relation.create(document, kind="contains", source_id=parent_symbol.id,
                target_id=None, target_ref=evidence.logical_id, observed=True, inferred=False, confidence=1.0,
                evidence_id=evidence.id, line=start + 1, metadata={"target_evidence_id": evidence.id}))


def parse_markdown(content: str, *, snapshot_id: str, file_path: str, max_chars: int = 1500) -> ParseResult:
    return MarkdownParser(max_chars).parse(SourceDocument(snapshot_id=snapshot_id, path=file_path,
                                                           content=content, language="markdown"))
