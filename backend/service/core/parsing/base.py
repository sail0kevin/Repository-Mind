"""ParserAdapter 抽象接口。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable

from service.core.parsing.models import ParseResult, SourceDocument


class ParserAdapter(ABC):
    """所有语言解析器必须实现的最小统一接口。"""

    languages: frozenset[str] = frozenset()
    extensions: frozenset[str] = frozenset()

    def supports(self, document: SourceDocument) -> bool:
        """根据显式语言或文件扩展名判断解析器是否适用。"""
        language = (document.language or "").lower()
        suffix = "." + document.path.rsplit(".", 1)[-1].lower() if "." in document.path else ""
        return language in self.languages or suffix in self.extensions

    @abstractmethod
    def parse(self, document: SourceDocument) -> ParseResult:
        """解析一个文档，任何语法错误都应转成 ParseResult.diagnostics。"""

    def post_process(self, results: Iterable[ParseResult]) -> list[ParseResult]:
        """默认不做跨文件处理，具体语言解析器可覆盖。"""
        return list(results)
