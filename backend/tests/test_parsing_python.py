"""M2 Python ParserAdapter 的结构化 fixture 测试。"""
from __future__ import annotations

from pathlib import Path

import pytest

from service.core.parsing.fallback_parser import FallbackParser
from service.core.parsing.models import SourceDocument
from service.core.parsing.python_parser import PythonParser
from service.core.parsing.registry import ParserRegistry, default_registry
from service.storage.snapshot_store import stable_snapshot_id

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "parsing"


@pytest.fixture
def python_documents() -> list[SourceDocument]:
    """从真实 fixture 文件创建同一 Snapshot 下的源码文档。"""
    snapshot_id = stable_snapshot_id("repo_fixture", "a" * 40)
    return [
        SourceDocument(
            snapshot_id=snapshot_id,
            path=path.relative_to(FIXTURE_ROOT).as_posix(),
            content=path.read_text(encoding="utf-8"),
            language="python",
        )
        for path in sorted(FIXTURE_ROOT.rglob("*.py"))
    ]


def test_python_parser_extracts_symbols_signatures_decorators_and_async(python_documents) -> None:
    """module/class/method/function/async、签名和装饰器必须完整提取。"""
    results = default_registry().parse_all(python_documents)
    service = next(item for item in results if item.document.path == "pkg/service.py")
    symbols = {item.qualified_name: item for item in service.symbols}

    assert symbols["pkg.service"].kind == "module"
    assert symbols["pkg.service.BaseService"].kind == "class"
    method = symbols["pkg.service.BaseService.run"]
    assert method.kind == "method"
    assert method.is_async is True
    assert method.signature == "async def run(self, value: int = 1, *, strict: bool = False) -> str"
    assert method.decorators == ('trace("service")',)
    assert symbols["pkg.service.helper"].signature == "def helper(name: str) -> str"
    assert all(symbol.evidence_id for symbol in service.symbols)


def test_relations_resolve_same_file_import_inheritance_and_cross_file_calls(python_documents) -> None:
    """同文件及明确 import 跨文件关系应绑定真实目标并保留证据。"""
    results = default_registry().parse_all(python_documents)
    service = next(item for item in results if item.document.path == "pkg/service.py")
    by_kind = {}
    for relation in service.relations:
        by_kind.setdefault(relation.kind, []).append(relation)

    assert any(item.target_qualified_name == "pkg.base.ExternalBase" and item.target_id for item in by_kind["inherits"])
    assert any(item.target_qualified_name == "pkg.base.external_call" and item.target_id for item in by_kind["calls"])
    assert any(item.target_qualified_name == "pkg.service.helper" and item.target_id for item in by_kind["calls"])
    assert all(item.observed is True for item in service.relations)
    assert all(item.inferred is (item.target_id is not None and item.kind != "contains")
               for item in service.relations)
    assert all(0.0 <= item.confidence <= 1.0 for item in service.relations)
    evidence_ids = {item.id for item in service.evidence}
    assert all(item.evidence_id in evidence_ids and item.line > 0 for item in service.relations)


def test_dynamic_and_ambiguous_calls_do_not_create_maybe_call_edges(python_documents) -> None:
    """动态调用和无法证明的裸名称不能产生 all-to-all 或 maybe_call。"""
    results = default_registry().parse_all(python_documents)
    service = next(item for item in results if item.document.path == "pkg/service.py")

    assert all(item.kind != "maybe_call" for item in service.relations)
    call_targets = {item.target_qualified_name for item in service.relations if item.kind == "calls"}
    assert "callback" not in call_targets
    assert "unknown" not in call_targets
    assert not any(target.endswith(".duplicate") for target in call_targets)


def test_syntax_error_is_isolated_to_one_file(python_documents) -> None:
    """坏文件只返回自己的诊断，其他文件继续解析和跨文件后处理。"""
    broken = SourceDocument(
        snapshot_id=python_documents[0].snapshot_id,
        path="pkg/broken.py",
        content="def broken(:\n    pass\n",
        language="python",
    )
    results = default_registry().parse_all([*python_documents, broken])
    broken_result = next(item for item in results if item.document.path == "pkg/broken.py")

    assert broken_result.succeeded is False
    assert broken_result.symbols == []
    assert broken_result.diagnostics[0].code == "python_syntax_error"
    assert any(item.succeeded and item.symbols for item in results if item is not broken_result)


def test_symbol_and_evidence_ids_are_stable_and_snapshot_scoped(python_documents) -> None:
    """同快照重复解析 ID 不漂移，不同快照必须产生不同 ID。"""
    parser = PythonParser()
    document = next(item for item in python_documents if item.path == "pkg/service.py")
    first = parser.parse(document)
    second = parser.parse(document)
    another = parser.parse(SourceDocument(
        snapshot_id="snap_other", path=document.path, content=document.content, language="python"
    ))

    assert [item.id for item in first.symbols] == [item.id for item in second.symbols]
    assert [item.id for item in first.evidence] == [item.id for item in second.evidence]
    assert {item.id for item in first.symbols}.isdisjoint(item.id for item in another.symbols)
    assert all(document.snapshot_id in (item.snapshot_id,) for item in first.symbols + first.evidence)


def test_relative_import_and_path_normalization() -> None:
    """Windows 路径应规范化，并正确解析包内相对 import。"""
    document = SourceDocument(
        snapshot_id="snap_test",
        path="pkg\\sub\\worker.py",
        content="from ..base import external_call\n\ndef run():\n    return external_call()\n",
        language="python",
    )
    result = PythonParser().parse(document)

    assert document.path == "pkg/sub/worker.py"
    assert any(item.target_qualified_name == "pkg.base.external_call" for item in result.relations)


def test_fallback_parser_keeps_whole_file_evidence() -> None:
    """不支持语言仍可进入统一模型，并给出非错误诊断。"""
    document = SourceDocument(snapshot_id="snap_x", path="notes.txt", content="hello\nworld")
    result = ParserRegistry([]).parse(document)

    assert isinstance(ParserRegistry([]).parser_for(document), FallbackParser)
    assert result.succeeded is True
    assert result.evidence[0].content == "hello\nworld"
    assert result.diagnostics[0].code == "unsupported_language"
