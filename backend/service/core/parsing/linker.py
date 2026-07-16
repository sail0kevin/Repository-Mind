"""确定性的全仓库关系绑定器。"""
from __future__ import annotations

from dataclasses import replace
from pathlib import PurePosixPath

from service.core.parsing.models import Diagnostic, ParseResult, Relation, Symbol


class RepositoryLinker:
    """只在目标唯一且可证明时连边；歧义和动态引用保留为未解析事实。"""

    def link(self, results: list[ParseResult]) -> list[ParseResult]:
        by_qname: dict[str, list[Symbol]] = {}
        by_name: dict[str, list[Symbol]] = {}
        modules: dict[str, list[Symbol]] = {}
        for result in results:
            for symbol in result.symbols:
                by_qname.setdefault(symbol.qualified_name, []).append(symbol)
                by_name.setdefault(symbol.name, []).append(symbol)
                if symbol.kind == "module":
                    modules.setdefault(symbol.qualified_name, []).append(symbol)

        for result in results:
            updated: list[Relation] = []
            for relation in result.relations:
                if relation.target_id or not relation.target_ref:
                    updated.append(relation)
                    continue
                candidates = list(by_qname.get(relation.target_ref, []))
                if relation.kind == "imports":
                    module_names = self._module_candidates(result.document.path, relation.target_ref)
                    candidates = [symbol for name in module_names for symbol in modules.get(name, [])]
                    if not candidates:
                        candidates = list(by_qname.get(relation.target_ref, []))
                elif relation.kind in {"calls", "inherits", "references", "exports"} and not candidates:
                    # 裸名只能绑定同文件定义。全仓唯一不代表源码有可见性依据。
                    if "." not in relation.target_ref and relation.target_ref not in {"this", "super"}:
                        candidates = [symbol for symbol in by_name.get(relation.target_ref, [])
                                      if symbol.path == result.document.path]
                if len(candidates) == 1:
                    updated.append(replace(relation.resolved(candidates[0].id, max(relation.confidence, 0.9)),
                                           inferred=True,
                                           resolver_status="resolved",
                                           metadata={**relation.metadata, "resolver_status": "resolved"}))
                else:
                    status = "ambiguous" if len(candidates) > 1 else "unresolved"
                    updated.append(replace(relation, resolver_status=status,
                                           metadata={**relation.metadata, "resolver_status": status}))
                    if len(candidates) > 1:
                        result.diagnostics.append(Diagnostic(
                            code="ambiguous_reference", message=f"引用 {relation.target_ref} 有 {len(candidates)} 个候选，未连边。",
                            severity="warning", path=result.document.path, line=relation.line,
                            column=relation.column, parser="repository-linker"))
            result.relations = updated
            result.sort_facts()
        return results

    @staticmethod
    def _module_candidates(path: str, target: str) -> list[str]:
        """把 Python 相对模块和 JS/TS 相对说明符解析为确定的模块候选。"""
        if target.startswith(".") and "/" in target or target.startswith("./") or target.startswith("../"):
            base = PurePosixPath(path).parent
            joined = base.joinpath(*target.split("/"))
            parts: list[str] = []
            for part in joined.parts:
                if part in {"", "."}:
                    continue
                if part == "..":
                    if not parts:
                        return []
                    parts.pop()
                else:
                    parts.append(part)
            normalized = PurePosixPath(*parts).as_posix()
            suffix = PurePosixPath(normalized).suffix.lower()
            candidates = [normalized] if suffix in {".js", ".jsx", ".ts", ".tsx"} else [
                f"{normalized}{extension}" for extension in (".js", ".jsx", ".ts", ".tsx")
            ]
            candidates.extend(f"{normalized}/index{extension}" for extension in (".js", ".jsx", ".ts", ".tsx"))
            return list(dict.fromkeys(candidates))
        if not target.startswith("."):
            return [target]
        level = len(target) - len(target.lstrip("."))
        suffix = target[level:]
        parts = list(PurePosixPath(path).with_suffix("").parts)
        if parts and parts[-1] == "__init__":
            parts.pop()
        else:
            parts = parts[:-1]
        keep = max(0, len(parts) - level + 1)
        return [".".join([*parts[:keep], *([suffix] if suffix else [])])]
