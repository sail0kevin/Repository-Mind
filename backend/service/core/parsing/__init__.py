"""M2 统一解析入口。"""

from service.core.parsing.base import ParserAdapter
from service.core.parsing.models import (
    Diagnostic,
    EvidenceUnit,
    ParseResult,
    Relation,
    SourceDocument,
    Symbol,
)
from service.core.parsing.registry import ParserRegistry, default_registry

__all__ = [
    "Diagnostic",
    "EvidenceUnit",
    "ParseResult",
    "ParserAdapter",
    "ParserRegistry",
    "Relation",
    "SourceDocument",
    "Symbol",
    "default_registry",
]
