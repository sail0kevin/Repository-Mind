"""统一解析层的数据模型。

ParserAdapter、存储层和兼容投影只使用这里的模型，避免各语言解析器各自定义事实结构。
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import json
from pathlib import PurePosixPath
from typing import Any, Literal

ParseStatus = Literal["parsed", "parsed_with_errors", "fallback_text", "unsupported", "failed"]
SymbolKind = Literal["module", "class", "interface", "function", "method", "variable", "section", "config_key"]
RelationKind = Literal["contains", "imports", "exports", "inherits", "calls", "references", "configures"]
DiagnosticSeverity = Literal["info", "warning", "error"]
ResolverStatus = Literal["resolved", "unresolved", "ambiguous", "unknown"]


def _digest(prefix: str, *parts: object) -> str:
    payload = json.dumps(parts, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return f"{prefix}_{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def stable_id(prefix: str, snapshot_id: str, *parts: object) -> str:
    """生成快照内记录 ID。"""
    return _digest(prefix, snapshot_id, *parts)


def logical_id(prefix: str, *parts: object) -> str:
    """生成跨快照稳定的逻辑 ID。"""
    return _digest(prefix, *parts)


@dataclass(frozen=True)
class SourceDocument:
    """scanner 单次读取后交给解析器的不可变文档。"""

    snapshot_id: str
    path: str
    content: str
    language: str | None = None
    repo_id: str | None = None
    file_id: str | None = None
    raw_bytes: bytes | None = None
    encoding: str = "utf-8"
    content_hash: str | None = None
    newline_style: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # 只移除明确的当前目录前缀，不能用 lstrip 误删 .github 等合法名称。
        raw_path = self.path.replace("\\", "/")
        while raw_path.startswith("./"):
            raw_path = raw_path[2:]
        pure = PurePosixPath(raw_path)
        if pure.is_absolute() or any(part == ".." for part in pure.parts):
            raise ValueError("path 必须是仓库根目录内的相对路径")
        normalized = pure.as_posix()
        if not self.snapshot_id.strip() or normalized in {"", "."}:
            raise ValueError("snapshot_id 和 path 不能为空")
        raw = self.raw_bytes if self.raw_bytes is not None else self.content.encode(self.encoding, errors="replace")
        newline = self.newline_style
        if newline is None:
            newline = "\r\n" if b"\r\n" in raw else ("\r" if b"\r" in raw else "\n")
        object.__setattr__(self, "path", normalized)
        object.__setattr__(self, "raw_bytes", raw)
        object.__setattr__(self, "content_hash", self.content_hash or hashlib.sha256(raw).hexdigest())
        object.__setattr__(self, "newline_style", newline)

    @property
    def newline(self) -> str:
        """兼容旧调用方的字段名。"""
        return self.newline_style or "\n"


@dataclass(frozen=True)
class EvidenceUnit:
    """可回溯到源码范围的规范证据事实。"""

    id: str
    logical_id: str
    snapshot_id: str
    path: str
    start_line: int
    end_line: int
    file_id: str | None = None
    start_column: int = 0
    end_column: int = 0
    kind: str = "source"
    content: str = ""
    symbol_id: str | None = None
    parent_id: str | None = None
    title: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(cls, document: SourceDocument, start_line: int, end_line: int, *, start_column: int = 0,
               end_column: int = 0, kind: str = "source", content: str = "", symbol_id: str | None = None,
               parent_id: str | None = None, title: str | None = None,
               metadata: dict[str, Any] | None = None, identity: object | None = None) -> "EvidenceUnit":
        safe_start = max(1, start_line)
        safe_end = max(safe_start, end_line)
        fact_metadata = metadata or {}
        # logical_id 使用结构身份而不是绝对行列，源码整体上下移动时仍保持稳定。
        structural_identity = identity if identity is not None else (
            fact_metadata.get("identity") or title or fact_metadata.get("key_path")
            or fact_metadata.get("symbol_name") or kind
        )
        logical_parts = (document.repo_id, document.path, kind, structural_identity)
        record_parts = (*logical_parts, safe_start, safe_end, max(0, start_column), max(0, end_column),
                        document.content_hash, hashlib.sha256(content.encode("utf-8")).hexdigest())
        return cls(
            id=stable_id("ev", document.snapshot_id, *record_parts), logical_id=logical_id("evl", *logical_parts),
            snapshot_id=document.snapshot_id, path=document.path, file_id=document.file_id, start_line=safe_start,
            end_line=safe_end, start_column=max(0, start_column),
            end_column=max(0, end_column), kind=kind, content=content, symbol_id=symbol_id,
            parent_id=parent_id, title=title, metadata=fact_metadata,
        )


@dataclass(frozen=True)
class Symbol:
    """语言无关的源码符号，同时携带跨快照逻辑 ID。"""

    id: str
    logical_id: str
    snapshot_id: str
    path: str
    name: str
    qualified_name: str
    kind: SymbolKind
    start_line: int
    end_line: int
    file_id: str | None = None
    start_column: int = 0
    end_column: int = 0
    signature: str | None = None
    decorators: tuple[str, ...] = ()
    is_async: bool = False
    parent_id: str | None = None
    evidence_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    discriminator: str | None = None

    @classmethod
    def create(cls, document: SourceDocument, **values: Any) -> "Symbol":
        discriminator = values.get("discriminator")
        logical_parts = (document.repo_id, document.path, values["kind"], values["qualified_name"], discriminator)
        record_parts = (*logical_parts, values.get("start_line", 1), values.get("end_line", 1),
                        values.get("start_column", 0), values.get("end_column", 0), values.get("signature"))
        return cls(id=stable_id("sym", document.snapshot_id, *record_parts),
                   logical_id=logical_id("syml", *logical_parts),
                   snapshot_id=document.snapshot_id, path=document.path, file_id=document.file_id, **values)


@dataclass(frozen=True)
class Relation:
    """有向关系；observed 与 inferred 可同时为真，未绑定目标时保留 target_ref。"""

    id: str
    snapshot_id: str
    kind: RelationKind
    source_id: str
    target_id: str | None
    target_ref: str | None
    observed: bool
    inferred: bool
    resolver_status: ResolverStatus
    confidence: float
    evidence_id: str
    path: str
    line: int
    file_id: str | None = None
    column: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def target_qualified_name(self) -> str:
        """兼容旧解析器字段名。"""
        return self.target_ref or ""

    @classmethod
    def create(cls, document: SourceDocument, **values: Any) -> "Relation":
        target_ref = values.pop("target_qualified_name", values.pop("target_ref", None))
        parts = (values["kind"], values["source_id"], values.get("target_id"), target_ref,
                 document.path, values["line"], values.get("column", 0))
        values.setdefault("resolver_status", "resolved" if values.get("target_id") else "unknown")
        return cls(id=stable_id("rel", document.snapshot_id, *parts), snapshot_id=document.snapshot_id,
                   path=document.path, file_id=document.file_id, target_ref=target_ref, **values)

    def resolved(self, target_id: str, confidence: float | None = None) -> "Relation":
        updated = replace(self, target_id=target_id, resolver_status="resolved",
                          confidence=self.confidence if confidence is None else confidence)
        parts = (self.kind, self.source_id, target_id, self.target_ref, self.path, self.line, self.column)
        return replace(updated, id=stable_id("rel", self.snapshot_id, *parts))


@dataclass(frozen=True)
class Diagnostic:
    """统一解析诊断范围，行号为 1-based inclusive。"""

    code: str
    message: str
    severity: DiagnosticSeverity
    path: str
    line: int | None = None
    column: int | None = None
    end_line: int | None = None
    end_column: int | None = None
    parser: str = "unknown"
    snapshot_id: str | None = None
    file_id: str | None = None

    @property
    def start_line(self) -> int | None:
        return self.line

    @property
    def start_column(self) -> int | None:
        return self.column


@dataclass
class ParseResult:
    """一个文档的全部局部事实；跨文件绑定由 RepositoryLinker 完成。"""

    document: SourceDocument
    status: ParseStatus = "parsed"
    symbols: list[Symbol] = field(default_factory=list)
    evidence: list[EvidenceUnit] = field(default_factory=list)
    relations: list[Relation] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        # 带语法错误的 fallback 仍可保存证据，但不能宣称该文件解析成功。
        return self.status in {"parsed", "fallback_text", "unsupported"}

    def sort_facts(self) -> None:
        """保证不同遍历顺序和平台下输出稳定。"""
        self.symbols.sort(key=lambda item: (item.path, item.start_line, item.start_column, item.qualified_name, item.id))
        self.evidence.sort(key=lambda item: (item.path, item.start_line, item.start_column, item.kind, item.id))
        self.relations.sort(key=lambda item: (item.path, item.line, item.column, item.kind, item.source_id, item.id))
        self.diagnostics.sort(key=lambda item: (item.path, item.start_line or 0, item.code, item.message))
