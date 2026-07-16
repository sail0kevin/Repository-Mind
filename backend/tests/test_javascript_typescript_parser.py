"""JS/TS tree-sitter ParserAdapter 测试。"""
from __future__ import annotations

from pathlib import Path

import pytest

from service.core.parsing.javascript_typescript_parser import JavaScriptTypeScriptParser
from service.core.parsing.models import SourceDocument
from service.core.parsing.registry import default_registry

FIXTURES = Path(__file__).parent / "fixtures" / "js_ts"


def _document(name: str, language: str) -> SourceDocument:
    """读取固定 fixture，避免测试执行任何目标 JavaScript。"""
    return SourceDocument(
        snapshot_id="snapshot-js-ts",
        path=f"src/{name}",
        content=(FIXTURES / name).read_text(encoding="utf-8"),
        language=language,
    )


def test_typescript_extracts_structures_and_observed_relations() -> None:
    """TS grammar 可用时提取结构；不可用时必须诚实 fallback。"""
    result = default_registry().parse(_document("sample.ts", "typescript"))
    if result.status == "fallback_text":
        assert result.diagnostics[0].code == "tree_sitter_unavailable"
        assert not result.symbols and not result.relations
        return

    symbols = {(item.kind, item.name) for item in result.symbols}
    assert ("interface", "Worker") in symbols
    assert ("class", "Service") in symbols
    assert ("method", "run") in symbols
    assert ("method", "finish") in symbols
    assert ("function", "launch") in symbols
    assert ("function", "main") in symbols

    relations = {(item.kind, item.target_qualified_name) for item in result.relations}
    assert ("imports", "./helpers") in relations
    assert ("exports", "Worker") in relations
    assert ("exports", "Service") in relations
    assert ("inherits", "BaseWorker") in relations
    assert ("inherits", "Parent") in relations
    assert ("calls", "renamed") in relations
    assert ("calls", "finish") in relations
    assert ("calls", "launch") in relations
    # 普通对象成员可能动态派发，不能伪装成精确直接调用。
    assert ("calls", "send") not in relations
    assert all(item.observed and not item.inferred for item in result.relations)
    assert not result.diagnostics


def test_javascript_is_registered_through_common_adapter() -> None:
    """JS 必须由统一注册表选择同一个 ParserAdapter。"""
    document = _document("sample.js", "javascript")
    registry = default_registry()
    assert isinstance(registry.parser_for(document), JavaScriptTypeScriptParser)

    result = registry.parse(document)
    if result.status == "fallback_text":
        assert result.diagnostics[0].code == "tree_sitter_unavailable"
        return
    assert {(item.kind, item.name) for item in result.symbols} >= {
        ("function", "helper"), ("class", "Plain"), ("method", "method")
    }
    assert ("calls", "helper") in {
        (item.kind, item.target_qualified_name) for item in result.relations
    }


def test_repository_linker_marks_unique_call_resolution_inferred() -> None:
    """唯一短名称绑定只能由独立 repository linker 完成，并标记为 inferred。"""
    results = default_registry().parse_all([
        _document("sample.ts", "typescript"),
        _document("sample.js", "javascript"),
    ])
    if all(result.status == "fallback_text" for result in results):
        assert all(result.diagnostics[0].code == "tree_sitter_unavailable" for result in results)
        return
    helper_calls = [
        relation
        for result in results
        for relation in result.relations
        if relation.kind == "calls" and relation.target_qualified_name == "helper"
    ]
    assert helper_calls
    assert all(item.observed and item.inferred and item.target_id for item in helper_calls)


def test_missing_native_dependency_has_explicit_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """原生依赖缺失时不做正则猜测，只返回整文件证据和诊断。"""
    import service.core.parsing.javascript_typescript_parser as module

    monkeypatch.setattr(module, "_TREE_SITTER_IMPORT_ERROR", ImportError("not installed"))
    result = JavaScriptTypeScriptParser().parse(_document("sample.ts", "typescript"))

    assert not result.symbols
    assert not result.relations
    assert len(result.evidence) == 1
    assert result.evidence[0].kind == "file"
    assert [item.code for item in result.diagnostics] == ["tree_sitter_unavailable"]


def test_syntax_error_is_diagnostic_not_process_failure() -> None:
    """坏文件只能产生文件级诊断，不能中断仓库解析。"""
    result = JavaScriptTypeScriptParser().parse(SourceDocument(
        snapshot_id="snapshot-broken",
        path="src/broken.ts",
        content="export function broken( {",
        language="typescript",
    ))
    if result.status == "fallback_text":
        assert result.diagnostics[0].code == "tree_sitter_unavailable"
    else:
        assert "tree_sitter_syntax_error" in {item.code for item in result.diagnostics}
