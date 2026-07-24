"""JavaScript/TypeScript 的 tree-sitter 结构化解析器。

本模块只读取源码并遍历语法树，不导入或执行目标仓库中的任何代码。
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from pathlib import PurePosixPath
from typing import Any

from service.core.parsing.base import ParserAdapter
from service.core.parsing.models import (
    Diagnostic,
    EvidenceUnit,
    ParseResult,
    Relation,
    SourceDocument,
    Symbol,
)

try:
    from tree_sitter import Language, Node, Parser
    import tree_sitter_javascript
    import tree_sitter_typescript
except (ImportError, OSError) as exc:  # pragma: no cover - 由无依赖测试覆盖结果，而非导入分支
    Language = Node = Parser = None  # type: ignore[assignment,misc]
    tree_sitter_javascript = tree_sitter_typescript = None
    _TREE_SITTER_IMPORT_ERROR: Exception | None = exc
else:
    _TREE_SITTER_IMPORT_ERROR = None


class JavaScriptTypeScriptParser(ParserAdapter):
    """使用官方 tree-sitter grammar 解析 JS、JSX、TS 和 TSX。"""

    languages = frozenset({"javascript", "typescript", "js", "jsx", "ts", "tsx"})
    extensions = frozenset({".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts"})

    def parse(self, document: SourceDocument) -> ParseResult:
        """解析单文件；依赖缺失时明确降级，绝不以正则冒充精确解析。"""
        if _TREE_SITTER_IMPORT_ERROR is not None or Parser is None or Language is None:
            return self._dependency_fallback(document, _TREE_SITTER_IMPORT_ERROR)

        source = document.content.encode("utf-8")
        try:
            parser = Parser(self._language_for(document.path))
            tree = parser.parse(source)
        except (AttributeError, TypeError, ValueError, OSError) as exc:
            return self._dependency_fallback(document, exc)

        result = ParseResult(document=document)
        self._symbol_ordinals: dict[tuple[str, str, str, str], int] = {}
        self._evidence_ordinals: dict[tuple[str, str], int] = {}
        module = self._add_symbol(result, tree.root_node, "module", self._module_name(document.path))
        self._visit_top_level(tree.root_node, result, module, source)
        if tree.root_node.has_error:
            error_node = next((node for node in self._walk(tree.root_node) if node.is_error or node.is_missing), tree.root_node)
            result.diagnostics.append(Diagnostic(
                code="tree_sitter_syntax_error",
                message="tree-sitter 检测到语法错误；已保留可可靠识别的结构。",
                severity="warning",
                path=document.path,
                line=error_node.start_point.row + 1,
                column=error_node.start_point.column,
                parser="tree-sitter-js-ts",
                snapshot_id=document.snapshot_id,
                file_id=document.file_id,
            ))
            result.status = "parsed_with_errors"
        return result

    def post_process(self, results: Iterable[ParseResult]) -> list[ParseResult]:
        """跨文件绑定统一交给 RepositoryLinker；Adapter 不做唯一名称猜测。"""
        return list(results)

    def _language_for(self, path: str) -> Any:
        """按扩展名选择 grammar；TSX 与 JSX 必须使用各自语法。"""
        suffix = PurePosixPath(path).suffix.lower()
        if suffix == ".tsx":
            capsule = tree_sitter_typescript.language_tsx()
        elif suffix in {".ts", ".mts", ".cts"}:
            capsule = tree_sitter_typescript.language_typescript()
        else:
            capsule = tree_sitter_javascript.language()
        return Language(capsule)

    def _dependency_fallback(self, document: SourceDocument, exc: Exception | None) -> ParseResult:
        """依赖不可用时只保留整文件证据，并返回机器可读诊断。"""
        lines = document.content.splitlines()
        evidence = EvidenceUnit.create(
            document, 1, max(1, len(lines)), kind="file", content=document.content,
            metadata={"parser": "fallback", "requested_parser": "tree-sitter-js-ts"},
        )
        detail = f"（{type(exc).__name__}: {exc}）" if exc else ""
        return ParseResult(
            document=document,
            status="fallback_text",
            evidence=[evidence],
            diagnostics=[Diagnostic(
                code="tree_sitter_unavailable",
                message=f"JS/TS tree-sitter 依赖不可用，已降级为整文件证据，未生成结构化符号或关系。{detail}",
                severity="warning",
                path=document.path,
                parser="tree-sitter-js-ts",
                snapshot_id=document.snapshot_id,
                file_id=document.file_id,
            )],
        )

    def _visit_top_level(self, root: Any, result: ParseResult, module: Symbol, source: bytes) -> None:
        """处理顶层声明、导入和导出；嵌套函数由声明处理器递归收集。"""
        for node in root.named_children:
            exported = node.type == "export_statement"
            declaration = next((child for child in node.named_children if child.type != "string"), None) if exported else node
            if node.type == "import_statement":
                self._add_import(result, module, node, source)
            elif exported:
                self._add_exports(result, module, node, declaration, source)
            if declaration is not None:
                self._add_declaration(result, module, declaration, source, exported=exported)

    def _add_declaration(
        self, result: ParseResult, parent: Symbol, node: Any, source: bytes, *, exported: bool = False
    ) -> None:
        """把 AST 声明转换为统一 Symbol，并提取其范围内的直接调用。"""
        if node.type in {"function_declaration", "generator_function_declaration"}:
            name_node = node.child_by_field_name("name")
            if name_node:
                symbol = self._add_symbol(result, node, "function", self._text(name_node, source), parent, exported)
                self._add_calls(result, symbol, node, source)
            return
        if node.type in {"class_declaration", "abstract_class_declaration"}:
            name_node = node.child_by_field_name("name")
            if not name_node:
                return
            symbol = self._add_symbol(result, node, "class", self._text(name_node, source), parent, exported)
            self._add_heritage(result, symbol, node, source)
            body = node.child_by_field_name("body") or next((c for c in node.named_children if c.type == "class_body"), None)
            if body:
                for child in body.named_children:
                    if child.type in {"method_definition", "method_signature", "abstract_method_signature"}:
                        method_name = child.child_by_field_name("name")
                        if method_name:
                            method = self._add_symbol(result, child, "method", self._text(method_name, source), symbol)
                            self._add_calls(result, method, child, source)
            return
        if node.type == "interface_declaration":
            name_node = node.child_by_field_name("name")
            if not name_node:
                return
            symbol = self._add_symbol(result, node, "interface", self._text(name_node, source), parent, exported)
            self._add_heritage(result, symbol, node, source)
            body = node.child_by_field_name("body") or next((c for c in node.named_children if c.type == "interface_body"), None)
            if body:
                for child in body.named_children:
                    if child.type == "method_signature":
                        method_name = child.child_by_field_name("name")
                        if method_name:
                            self._add_symbol(result, child, "method", self._text(method_name, source), symbol)
            return
        if node.type in {"lexical_declaration", "variable_declaration"}:
            for declarator in (c for c in node.named_children if c.type == "variable_declarator"):
                value = declarator.child_by_field_name("value")
                name_node = declarator.child_by_field_name("name")
                if value and name_node and value.type in {"arrow_function", "function_expression", "generator_function"}:
                    symbol = self._add_symbol(result, declarator, "function", self._text(name_node, source), parent, exported)
                    self._add_calls(result, symbol, value, source)

    def _add_import(self, result: ParseResult, module: Symbol, node: Any, source: bytes) -> None:
        """记录静态 import 的模块说明符，不尝试解析 Node.js 模块搜索规则。"""
        specifier = next((child for child in node.named_children if child.type == "string"), None)
        if specifier is None:
            return
        target = self._unquote(self._text(specifier, source))
        evidence = self._add_evidence(
            result, node, "import", source, module.id,
            identity=(module.id, self._next_evidence_discriminator(module.id, "import")),
        )
        result.relations.append(Relation.create(
            result.document, kind="imports", source_id=module.id, target_id=None,
            target_qualified_name=target, observed=True, inferred=False, confidence=1.0,
            evidence_id=evidence.id, line=node.start_point.row + 1, column=node.start_point.column,
            metadata={"syntax": "static_import"},
        ))

    def _add_exports(self, result: ParseResult, module: Symbol, node: Any, declaration: Any, source: bytes) -> None:
        """记录 export 语句；声明导出会在符号创建后补充精确目标。"""
        evidence = self._add_evidence(
            result, node, "export", source, module.id,
            identity=(module.id, self._next_evidence_discriminator(module.id, "export")),
        )
        names: list[str] = []
        if declaration is not None:
            name_node = declaration.child_by_field_name("name")
            if name_node:
                names.append(self._text(name_node, source))
            elif declaration.type in {"lexical_declaration", "variable_declaration"}:
                names.extend(
                    self._text(name, source)
                    for item in declaration.named_children if item.type == "variable_declarator"
                    for name in [item.child_by_field_name("name")] if name is not None
                )
        for specifier in (item for item in self._walk(node) if item.type == "export_specifier"):
            name = specifier.child_by_field_name("alias") or specifier.child_by_field_name("name")
            if name:
                names.append(self._text(name, source))
        if not names and any(child.type == "*" for child in node.children):
            names.append("*")
        for name in dict.fromkeys(names):
            result.relations.append(Relation.create(
                result.document, kind="exports", source_id=module.id, target_id=None,
                target_qualified_name=name, observed=True, inferred=False, confidence=1.0,
                evidence_id=evidence.id, line=node.start_point.row + 1, column=node.start_point.column,
                metadata={"default": "default" in self._text(node, source).split()},
            ))

    def _add_heritage(self, result: ParseResult, symbol: Symbol, node: Any, source: bytes) -> None:
        """记录 extends/implements 语法，端点留给后处理或上层解析。"""
        for clause in (item for item in self._walk(node) if item.type in {"extends_clause", "extends_type_clause", "implements_clause"}):
            for target in clause.named_children:
                if target.type in {"identifier", "type_identifier", "generic_type", "member_expression", "nested_type_identifier"}:
                    evidence = self._add_evidence(
                        result, clause, "relation", source, symbol.id,
                        identity=(symbol.id, self._next_evidence_discriminator(symbol.id, "relation")),
                    )
                    result.relations.append(Relation.create(
                        result.document, kind="inherits", source_id=symbol.id, target_id=None,
                        target_qualified_name=self._text(target, source), observed=True, inferred=False,
                        confidence=1.0, evidence_id=evidence.id, line=target.start_point.row + 1,
                        column=target.start_point.column,
                        metadata={"clause": clause.type},
                    ))

    def _add_calls(self, result: ParseResult, caller: Symbol, scope: Any, source: bytes) -> None:
        """只提取可直接命名的调用：foo() 与 this.foo()；跳过 obj.foo() 动态派发。"""
        nested_declarations = {"function_declaration", "function_expression", "arrow_function", "method_definition"}
        stack = list(reversed(scope.named_children))
        while stack:
            node = stack.pop()
            if node is not scope and node.type in nested_declarations:
                continue
            if node.type == "call_expression":
                callee = node.child_by_field_name("function")
                target = self._direct_callee(callee, source)
                if target:
                    evidence = self._add_evidence(
                        result, node, "call", source, caller.id,
                        identity=(caller.id, self._next_evidence_discriminator(caller.id, "call")),
                    )
                    result.relations.append(Relation.create(
                        result.document, kind="calls", source_id=caller.id, target_id=None,
                        target_qualified_name=target, observed=True, inferred=False, confidence=0.85,
                        evidence_id=evidence.id, line=node.start_point.row + 1, column=node.start_point.column,
                        metadata={"syntax": "direct_call"},
                    ))
            stack.extend(reversed(node.named_children))

    def _direct_callee(self, callee: Any, source: bytes) -> str | None:
        """返回静态可命名被调方；普通对象成员可能动态变化，因此不猜测。"""
        if callee is None:
            return None
        if callee.type in {"identifier", "type_identifier"}:
            return self._text(callee, source)
        if callee.type == "member_expression":
            obj = callee.child_by_field_name("object")
            prop = callee.child_by_field_name("property")
            if obj is not None and prop is not None and obj.type in {"this", "super"}:
                return self._text(prop, source)
        return None

    def _add_symbol(
        self, result: ParseResult, node: Any, kind: str, name: str,
        parent: Symbol | None = None, exported: bool = False,
    ) -> Symbol:
        """创建符号、源码证据和 contains 关系。"""
        qualified = f"{parent.qualified_name}.{name}" if parent else name
        signature = self._signature(node, result.document.content.encode("utf-8"))
        parent_key = parent.logical_id if parent else result.document.path
        ordinal_key = (parent_key, kind, name, "definition")
        ordinal = self._symbol_ordinals.get(ordinal_key, 0)
        self._symbol_ordinals[ordinal_key] = ordinal + 1
        discriminator = f"{kind}:{name}:{ordinal}"
        symbol = Symbol.create(
            result.document, name=name, qualified_name=qualified, kind=kind,
            start_line=node.start_point.row + 1, end_line=node.end_point.row + 1,
            start_column=node.start_point.column, end_column=node.end_point.column,
            signature=signature, parent_id=parent.id if parent else None, discriminator=discriminator,
            metadata={"exported": exported, "parser": "tree-sitter"},
        )
        evidence = self._add_evidence(
            result, node, kind, result.document.content.encode("utf-8"), symbol.id,
            identity=(qualified, discriminator),
        )
        symbol = replace(symbol, evidence_id=evidence.id)
        result.symbols.append(symbol)
        if parent:
            result.relations.append(Relation.create(
                result.document, kind="contains", source_id=parent.id, target_id=symbol.id,
                target_qualified_name=symbol.qualified_name, observed=True, inferred=False,
                confidence=1.0, evidence_id=evidence.id, line=symbol.start_line,
                column=symbol.start_column,
            ))
        return symbol

    def _next_evidence_discriminator(self, owner_id: str, kind: str) -> int:
        """按 (owner_id, kind) 分配自增序号，避免同一符号下同类证据的 logical_id 相撞。

        `_add_symbol` 已用 `_symbol_ordinals` 保证符号定义的 identity 唯一；
        但 export/relation/call 证据默认的 structural_identity 只回退到裸 kind
        字符串，同一模块/符号内出现第二条同类证据时就会与第一条拥有同样的
        logical_id，撞上 evidence_units 的 UNIQUE(snapshot_id, identity_key)。
        """
        ordinal_key = (owner_id, kind)
        ordinal = self._evidence_ordinals.get(ordinal_key, 0)
        self._evidence_ordinals[ordinal_key] = ordinal + 1
        return ordinal

    def _add_evidence(self, result: ParseResult, node: Any, kind: str, source: bytes, symbol_id: str,
                      identity: object | None = None) -> EvidenceUnit:
        """按 tree-sitter 的字节范围创建可回溯证据。"""
        evidence = EvidenceUnit.create(
            result.document, node.start_point.row + 1, node.end_point.row + 1,
            start_column=node.start_point.column, end_column=node.end_point.column,
            kind=kind, content=self._text(node, source), symbol_id=symbol_id, identity=identity,
            metadata={"parser": "tree-sitter"},
        )
        result.evidence.append(evidence)
        return evidence

    def _signature(self, node: Any, source: bytes) -> str | None:
        """截取声明头作为签名，避免把完整函数体重复写入元数据。"""
        text = self._text(node, source)
        brace = text.find("{")
        return text[:brace].strip() if brace >= 0 else text.splitlines()[0].strip()

    @staticmethod
    def _module_name(path: str) -> str:
        return PurePosixPath(path).as_posix()

    @staticmethod
    def _text(node: Any, source: bytes) -> str:
        return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")

    @staticmethod
    def _unquote(value: str) -> str:
        return value[1:-1] if len(value) >= 2 and value[0] in {'"', "'", "`"} and value[-1] == value[0] else value

    @staticmethod
    def _walk(node: Any) -> Iterable[Any]:
        stack = [node]
        while stack:
            current = stack.pop()
            yield current
            stack.extend(reversed(current.named_children))
