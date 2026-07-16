"""基于 Python 标准库 AST 的结构化解析器。"""
from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import PurePosixPath
from typing import Iterable

from service.core.parsing.base import ParserAdapter
from service.core.parsing.models import (
    Diagnostic, EvidenceUnit, ParseResult, Relation, SourceDocument, Symbol,
)


class PythonParser(ParserAdapter):
    """提取 Python 定义、导入、继承和可静态确认的调用。"""

    languages = frozenset({"python", "py"})
    extensions = frozenset({".py", ".pyi"})

    def parse(self, document: SourceDocument) -> ParseResult:
        """解析单文件；SyntaxError 只生成该文件诊断。"""
        result = ParseResult(document=document)
        try:
            tree = ast.parse(document.content, filename=document.path, type_comments=True)
        except SyntaxError as exc:
            result.diagnostics.append(Diagnostic(
                code="python_syntax_error",
                message=exc.msg,
                severity="error",
                path=document.path,
                line=exc.lineno,
                column=exc.offset,
                parser="python-ast",
                snapshot_id=document.snapshot_id,
                file_id=document.file_id,
            ))
            result.status = "parsed_with_errors"
            result.evidence.append(EvidenceUnit.create(
                document, 1, max(1, len(document.content.splitlines())), kind="fallback",
                content=document.content, title=document.path, identity=("syntax-error-file", document.path),
                metadata={"parser": "python-ast", "parse_error": exc.msg},
            ))
            return result
        except (ValueError, UnicodeError) as exc:
            result.diagnostics.append(Diagnostic(
                code="python_parse_error", message=str(exc), severity="error", path=document.path,
                parser="python-ast", snapshot_id=document.snapshot_id, file_id=document.file_id,
            ))
            result.status = "failed"
            return result

        module_name = self._module_name(document.path)
        module_symbol = Symbol.create(
            document,
            name=module_name.rsplit(".", 1)[-1],
            qualified_name=module_name,
            kind="module",
            start_line=1,
            end_line=max(1, len(document.content.splitlines())),
            signature=None,
            metadata={"module_name": module_name},
        )
        module_evidence = self._evidence(document, tree, "module", document.content, module_symbol.id)
        module_symbol = replace(module_symbol, evidence_id=module_evidence.id)
        result.symbols.append(module_symbol)
        result.evidence.append(module_evidence)

        collector = _PythonCollector(document, result, module_symbol, module_name, tree)
        collector.visit(tree)
        return result

    def post_process(self, results: Iterable[ParseResult]) -> list[ParseResult]:
        """跨文件绑定统一交给 RepositoryLinker，Adapter 只产出局部事实。"""
        return list(results)

    @staticmethod
    def _module_name(path: str) -> str:
        """把 Python 路径转换成 import 使用的模块名。"""
        pure = PurePosixPath(path)
        parts = list(pure.with_suffix("").parts)
        if parts and parts[-1] == "__init__":
            parts.pop()
        return ".".join(parts) or pure.stem

    @staticmethod
    def _evidence(
        document: SourceDocument, node: ast.AST, kind: str, content: str, symbol_id: str | None = None
    ) -> EvidenceUnit:
        """根据 AST 节点创建精确源码证据。"""
        return EvidenceUnit.create(
            document,
            getattr(node, "lineno", 1),
            getattr(node, "end_lineno", max(1, len(document.content.splitlines()))),
            start_column=getattr(node, "col_offset", 0),
            end_column=getattr(node, "end_col_offset", 0),
            kind=kind,
            content=content,
            symbol_id=symbol_id,
        )


class _PythonCollector(ast.NodeVisitor):
    """在一个文件内维护作用域、导入别名和局部绑定。"""

    def __init__(
        self,
        document: SourceDocument,
        result: ParseResult,
        module: Symbol,
        module_name: str,
        tree: ast.Module,
    ) -> None:
        self.document = document
        self.result = result
        self.module = module
        self.module_name = module_name
        self.scope: list[Symbol] = [module]
        self.imports: dict[str, str] = {}
        self.local_symbols: dict[str, Symbol] = {}
        self.class_symbols: dict[str, Symbol] = {}
        self.symbol_ordinals: dict[tuple[str, str, str], int] = {}
        self.relation_ordinals: dict[tuple[str, str, str], int] = {}
        # 先收集模块级定义，保证函数可以调用定义在其后方的函数。
        for child in tree.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualified = f"{module_name}.{child.name}"
                self.local_symbols[child.name] = Symbol.create(
                    document,
                    name=child.name,
                    qualified_name=qualified,
                    kind="function",
                    start_line=child.lineno,
                    end_line=getattr(child, "end_lineno", child.lineno),
                )
            elif isinstance(child, ast.ClassDef):
                qualified = f"{module_name}.{child.name}"
                self.class_symbols[child.name] = Symbol.create(
                    document,
                    name=child.name,
                    qualified_name=qualified,
                    kind="class",
                    start_line=child.lineno,
                    end_line=getattr(child, "end_lineno", child.lineno),
                )

    def visit_Import(self, node: ast.Import) -> None:
        """记录 import package.mod 及其别名。"""
        for ordinal, alias in enumerate(node.names):
            local = alias.asname or alias.name.split(".", 1)[0]
            self.imports[local] = alias.name
            alias_identity = ("import", alias.name, alias.asname, local, ordinal)
            self._add_relation("imports", self.module, alias.name, node, observed=True, inferred=False,
                               confidence=1.0, evidence_identity=alias_identity)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """解析绝对与相对 from import 的限定名。"""
        base = self._resolve_import_module(node.module or "", node.level)
        for ordinal, alias in enumerate(node.names):
            if alias.name == "*":
                continue
            target = f"{base}.{alias.name}" if base else alias.name
            local = alias.asname or alias.name
            self.imports[local] = target
            alias_identity = ("from-import", base, alias.name, alias.asname, local, ordinal)
            self._add_relation("imports", self.module, target, node, observed=True, inferred=False,
                               confidence=1.0, evidence_identity=alias_identity)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """提取类、装饰器、父类和类体方法。"""
        symbol = self._add_symbol(node, "class", is_async=False)
        self.class_symbols[node.name] = symbol
        for base in node.bases:
            target = self._resolve_expr(base)
            if target:
                self._add_relation("inherits", symbol, target, base, observed=True, inferred=False, confidence=0.95)
        self.scope.append(symbol)
        for child in node.body:
            self.visit(child)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """提取同步函数或方法。"""
        self._visit_function(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """提取异步函数或方法。"""
        self._visit_function(node, is_async=True)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef, is_async: bool) -> None:
        kind = "method" if self.scope[-1].kind == "class" else "function"
        symbol = self._add_symbol(node, kind, is_async=is_async)
        if self.scope[-1].kind == "module":
            self.local_symbols[node.name] = symbol
        self.scope.append(symbol)
        for child in node.body:
            self.visit(child)
        self.scope.pop()

    def visit_Call(self, node: ast.Call) -> None:
        """仅输出名称能由当前作用域或 import 绑定静态解析的调用。"""
        target = self._resolve_call(node.func)
        if target and self.scope[-1].kind in {"function", "method"}:
            self._add_relation("calls", self.scope[-1], target, node.func, observed=True, inferred=False, confidence=0.95)
        self.generic_visit(node)

    def _add_symbol(self, node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef, kind: str, is_async: bool) -> Symbol:
        parent = self.scope[-1]
        qualified = f"{parent.qualified_name}.{node.name}"
        source = ast.get_source_segment(self.document.content, node) or ""
        signature = self._signature(node) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else None
        ordinal_key = (parent.id, kind, node.name)
        ordinal = self.symbol_ordinals.get(ordinal_key, 0)
        self.symbol_ordinals[ordinal_key] = ordinal + 1
        discriminator = f"{kind}:{node.name}:{ordinal}"
        symbol = Symbol.create(
            self.document,
            name=node.name,
            qualified_name=qualified,
            kind=kind,
            start_line=node.lineno,
            end_line=getattr(node, "end_lineno", node.lineno),
            start_column=node.col_offset,
            end_column=getattr(node, "end_col_offset", 0),
            signature=signature,
            decorators=tuple(self._expr_text(item) for item in node.decorator_list),
            is_async=is_async,
            parent_id=parent.id,
            discriminator=discriminator,
        )
        evidence = EvidenceUnit.create(
            self.document, node.lineno, getattr(node, "end_lineno", node.lineno),
            start_column=node.col_offset, end_column=getattr(node, "end_col_offset", 0),
            kind=kind, content=source, symbol_id=symbol.id,
            identity=(qualified, discriminator), metadata={"symbol_name": qualified},
        )
        symbol = replace(symbol, evidence_id=evidence.id)
        self.result.symbols.append(symbol)
        self.result.evidence.append(evidence)
        self._add_relation("contains", parent, qualified, node, target_id=symbol.id, observed=True, inferred=False, confidence=1.0)
        return symbol

    def _add_relation(
        self,
        kind: str,
        source: Symbol,
        target_qname: str,
        node: ast.AST,
        *,
        target_id: str | None = None,
        observed: bool,
        inferred: bool,
        confidence: float,
        evidence_identity: object | None = None,
    ) -> None:
        content = ast.get_source_segment(self.document.content, node) or target_qname
        relation_key = (source.id, kind, target_qname)
        ordinal = self.relation_ordinals.get(relation_key, 0)
        self.relation_ordinals[relation_key] = ordinal + 1
        evidence = EvidenceUnit.create(
            self.document, getattr(node, "lineno", source.start_line),
            getattr(node, "end_lineno", getattr(node, "lineno", source.end_line)),
            start_column=getattr(node, "col_offset", 0), end_column=getattr(node, "end_col_offset", 0),
            kind=f"relation:{kind}", content=content, symbol_id=source.id,
            identity=evidence_identity or (source.logical_id, kind, target_qname, ordinal),
        )
        self.result.evidence.append(evidence)
        self.result.relations.append(Relation.create(
            self.document,
            kind=kind,
            source_id=source.id,
            target_id=target_id,
            target_qualified_name=target_qname,
            observed=observed,
            inferred=inferred,
            confidence=confidence,
            evidence_id=evidence.id,
            line=getattr(node, "lineno", source.start_line),
            column=getattr(node, "col_offset", 0),
        ))

    def _resolve_call(self, node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            if node.id in self.local_symbols:
                return self.local_symbols[node.id].qualified_name
            return self.imports.get(node.id)
        if isinstance(node, ast.Attribute):
            return self._resolve_expr(node)
        return None

    def _resolve_expr(self, node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            if node.id in self.class_symbols:
                return self.class_symbols[node.id].qualified_name
            return self.imports.get(node.id)
        if isinstance(node, ast.Attribute):
            base = self._resolve_expr(node.value)
            return f"{base}.{node.attr}" if base else None
        return None

    def _resolve_import_module(self, module: str, level: int) -> str:
        if level == 0:
            return module
        package = self.module_name.split(".")[:-1]
        keep = max(0, len(package) - level + 1)
        prefix = package[:keep]
        if module:
            prefix.extend(module.split("."))
        return ".".join(prefix)

    def _signature(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        """用 AST 源码还原参数、返回注解和 async 标记。"""
        args = node.args
        positional = [*args.posonlyargs, *args.args]
        defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
        rendered: list[str] = []
        for index, (argument, default) in enumerate(zip(positional, defaults)):
            text = argument.arg
            if argument.annotation:
                text += f": {self._expr_text(argument.annotation)}"
            if default is not None:
                text += f" = {self._expr_text(default)}"
            rendered.append(text)
            if args.posonlyargs and index + 1 == len(args.posonlyargs):
                rendered.append("/")
        if args.vararg:
            text = "*" + args.vararg.arg
            if args.vararg.annotation:
                text += f": {self._expr_text(args.vararg.annotation)}"
            rendered.append(text)
        elif args.kwonlyargs:
            rendered.append("*")
        for argument, default in zip(args.kwonlyargs, args.kw_defaults):
            text = argument.arg
            if argument.annotation:
                text += f": {self._expr_text(argument.annotation)}"
            if default is not None:
                text += f" = {self._expr_text(default)}"
            rendered.append(text)
        if args.kwarg:
            text = "**" + args.kwarg.arg
            if args.kwarg.annotation:
                text += f": {self._expr_text(args.kwarg.annotation)}"
            rendered.append(text)
        prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        returns = f" -> {self._expr_text(node.returns)}" if node.returns else ""
        return f"{prefix} {node.name}({', '.join(rendered)}){returns}"

    def _expr_text(self, node: ast.AST) -> str:
        return ast.get_source_segment(self.document.content, node) or ast.unparse(node)
