"""不支持语言的安全降级解析器。"""
from __future__ import annotations

from service.core.parsing.base import ParserAdapter
from service.core.parsing.models import Diagnostic, EvidenceUnit, ParseResult, SourceDocument


class FallbackParser(ParserAdapter):
    """保留整文件证据，但明确说明没有结构化语义。"""

    def supports(self, document: SourceDocument) -> bool:
        """Fallback 总能处理文档，因此必须放在注册表最后。"""
        return True

    def parse(self, document: SourceDocument) -> ParseResult:
        """把普通文本保存为一个证据单元。"""
        lines = document.content.splitlines()
        evidence = EvidenceUnit.create(
            document,
            1,
            max(1, len(lines)),
            kind="file",
            content=document.content,
        )
        return ParseResult(
            document=document,
            status="unsupported",
            evidence=[evidence],
            diagnostics=[Diagnostic(
                code="unsupported_language",
                message="当前文件没有结构化解析器，已降级为整文件证据。",
                severity="info",
                path=document.path,
            )],
        )
