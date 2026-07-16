"""解析器注册表和批量解析入口。"""
from __future__ import annotations

from collections.abc import Iterable

from service.core.parsing.base import ParserAdapter
from service.core.parsing.fallback_parser import FallbackParser
from service.core.parsing.models import Diagnostic, ParseResult, SourceDocument
from service.core.parsing.linker import RepositoryLinker


class ParserRegistry:
    """按注册顺序选择解析器，并按解析器执行跨文件后处理。"""

    def __init__(self, parsers: Iterable[ParserAdapter] | None = None) -> None:
        self._parsers = list(parsers or [])
        self._fallback = FallbackParser()

    def register(self, parser: ParserAdapter) -> None:
        """注册具体语言解析器。"""
        self._parsers.append(parser)

    def parser_for(self, document: SourceDocument) -> ParserAdapter:
        """返回第一个支持文档的解析器，否则安全降级。"""
        return next((parser for parser in self._parsers if parser.supports(document)), self._fallback)

    def parse(self, document: SourceDocument) -> ParseResult:
        """解析单个文件。"""
        return self.parser_for(document).parse(document)

    def parse_all(self, documents: Iterable[SourceDocument]) -> list[ParseResult]:
        """先完成所有文件的局部解析，再统一执行确定性 repository linker。"""
        ordered: list[ParseResult] = []
        for document in documents:
            parser = self.parser_for(document)
            try:
                ordered.append(parser.parse(document))
            except Exception as exc:  # 单文件适配器故障不能中断整个仓库。
                ordered.append(ParseResult(
                    document=document,
                    status="failed",
                    diagnostics=[Diagnostic(
                        code="parser_failed", message=f"{type(exc).__name__}: {exc}", severity="error",
                        path=document.path, parser=type(parser).__name__, snapshot_id=document.snapshot_id,
                        file_id=document.file_id,
                    )],
                ))
        return RepositoryLinker().link(ordered)


def default_registry() -> ParserRegistry:
    """创建内置解析器注册表；依赖缺失由各 Adapter 诚实 fallback。"""
    from service.core.parsing.config_adapter import ConfigParser
    from service.core.parsing.javascript_typescript_parser import JavaScriptTypeScriptParser
    from service.core.parsing.markdown_adapter import MarkdownParser
    from service.core.parsing.python_parser import PythonParser

    return ParserRegistry([PythonParser(), JavaScriptTypeScriptParser(), MarkdownParser(), ConfigParser()])
