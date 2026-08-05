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


def test_actual_mcp_impact_wrapper_has_a_resolved_static_call_to_the_specialist() -> None:
    """真实 MCP 工具可导航至其静态解析到的 Specialist Tool 调用。"""
    backend_root = Path(__file__).resolve().parents[1]
    documents = [
        SourceDocument(
            snapshot_id="snap", path="backend/service/mcp_server/tools.py",
            content=(backend_root / "service/mcp_server/tools.py").read_text(encoding="utf-8"),
            language="python",
        ),
        SourceDocument(
            snapshot_id="snap", path="backend/service/core/agent/tools.py",
            content=(backend_root / "service/core/agent/tools.py").read_text(encoding="utf-8"),
            language="python",
        ),
    ]

    mcp_result = next(
        item for item in default_registry().parse_all(documents)
        if item.document.path == "backend/service/mcp_server/tools.py"
    )
    mcp_symbol = next(item for item in mcp_result.symbols if item.name == "analyze_impact")
    specialist_call = next(
        item for item in mcp_result.relations
        if item.kind == "calls"
        and item.source_id == mcp_symbol.id
        and item.target_qualified_name == "service.core.agent.tools.dependency_impact"
    )

    assert specialist_call.target_id is not None
    assert specialist_call.resolver_status == "resolved"
    assert specialist_call.metadata["resolution_method"] == "source_root_suffix"


def test_imported_class_constructor_method_resolves_through_package_reexport() -> None:
    """MCP wrappers can navigate from a package re-export to the actual method."""
    documents = [
        SourceDocument(
            snapshot_id="snap", path="backend/mcp.py",
            content="from service.retrieval import Retriever\n\ndef search():\n    return Retriever().retrieve()\n",
            language="python",
        ),
        SourceDocument(
            snapshot_id="snap", path="backend/service/retrieval/__init__.py",
            content="from service.retrieval.impl import Retriever\n",
            language="python",
        ),
        SourceDocument(
            snapshot_id="snap", path="backend/service/retrieval/impl.py",
            content="class Retriever:\n    def retrieve(self):\n        return []\n",
            language="python",
        ),
        SourceDocument(
            snapshot_id="snap", path="backend/factory.py",
            content="from service.retrieval import make_retriever\n\ndef search():\n    return make_retriever().retrieve()\n",
            language="python",
        ),
    ]

    results = default_registry().parse_all(documents)
    mcp_result = next(item for item in results if item.document.path == "backend/mcp.py")
    search = next(item for item in mcp_result.symbols if item.name == "search")
    call = next(item for item in mcp_result.relations if item.kind == "calls" and item.source_id == search.id)

    assert call.target_qualified_name == "service.retrieval.Retriever.retrieve"
    assert call.target_id is not None
    assert call.resolver_status == "resolved"
    assert call.metadata["resolution_method"] == "imported_constructor_method"

    factory_result = next(item for item in results if item.document.path == "backend/factory.py")
    factory_call = next(item for item in factory_result.relations if item.kind == "calls")
    assert factory_call.target_id is None
    assert factory_call.resolver_status == "unresolved"


def test_oversized_function_splits_at_nested_definition_boundaries() -> None:
    """超长函数应按嵌套定义边界拆分成多条 Evidence，保持语义相干。"""
    from service.core.evidence.budget import estimate_tokens

    # 构造超长函数：嵌套定义分布在函数体中间，把函数切成多段。
    body_lines = ["def big_function():"]
    # 第一段：30 行主体。
    for i in range(30):
        body_lines.append(f"    total += compute_value_{i}({'x' * 20})  # accumulate")
    # 嵌套定义 1：应成为切分边界。
    body_lines.append("    def inner_helper():")
    body_lines.append("        return total * 2")
    body_lines.append("")
    # 第二段：30 行主体。
    for i in range(30, 60):
        body_lines.append(f"    total += compute_value_{i}({'x' * 20})  # accumulate")
    # 嵌套定义 2：应成为切分边界。
    body_lines.append("    class InnerState:")
    body_lines.append("        def __init__(self):")
    body_lines.append("            self.value = inner_helper()")
    body_lines.append("")
    # 第三段：20 行主体。
    for i in range(60, 80):
        body_lines.append(f"    total += compute_value_{i}({'x' * 20})  # accumulate")
    body_lines.append("    return InnerState()")
    source = "\n".join(body_lines)

    doc = SourceDocument(snapshot_id="snap", path="big.py", content=source, language="python")
    result = PythonParser().parse(doc)

    # 找到 big_function 对应的 Evidence（symbol_name 是 qualified name）。
    big_evidence = [e for e in result.evidence if e.metadata.get("symbol_name") == "big.big_function"]
    # 超长函数应被拆成多条（而不是 1 条巨大的）。
    assert len(big_evidence) >= 2, f"超长函数应被拆分，实际 {len(big_evidence)} 条"
    # 每条都比原始（~1200 token）小，且包含函数头的第一片应明显小于整体。
    original_tokens = estimate_tokens(source)
    for chunk in big_evidence:
        assert estimate_tokens(chunk.content) < original_tokens
    # 所有切片的 logical_id 应唯一。
    logical_ids = [e.logical_id for e in big_evidence]
    assert len(logical_ids) == len(set(logical_ids))
    # 嵌套定义 inner_helper 和 InnerState 应作为独立 Symbol 存在。
    nested_names = {s.name for s in result.symbols if s.name in {"inner_helper", "InnerState"}}
    assert nested_names == {"inner_helper", "InnerState"}


def test_oversized_function_without_nested_defs_falls_back_to_line_split() -> None:
    """无嵌套定义的超长函数应回退到行级均匀切片。"""
    from service.core.evidence.budget import estimate_tokens
    from service.core.parsing.python_parser import _MAX_FUNCTION_TOKENS

    body_lines = ["def huge_single_function():"]
    for i in range(200):
        body_lines.append(f"    result_{i} = process_item_{i}({'y' * 25})  # work")
    body_lines.append("    return result_199")
    source = "\n".join(body_lines)

    doc = SourceDocument(snapshot_id="snap", path="huge.py", content=source, language="python")
    result = PythonParser().parse(doc)

    big_evidence = [e for e in result.evidence if e.metadata.get("symbol_name") == "huge.huge_single_function"]
    assert len(big_evidence) >= 2, f"应回退到行级拆分，实际 {len(big_evidence)} 条"
    for chunk in big_evidence:
        assert estimate_tokens(chunk.content) <= _MAX_FUNCTION_TOKENS + 100


def test_short_function_is_not_split() -> None:
    """未超预算的函数应保持单条 Evidence。"""
    source = (
        "def short():\n"
        "    x = 1\n"
        "    y = 2\n"
        "    return x + y\n"
    )
    doc = SourceDocument(snapshot_id="snap", path="short.py", content=source, language="python")
    result = PythonParser().parse(doc)

    short_evidence = [e for e in result.evidence if e.metadata.get("symbol_name") == "short.short"]
    assert len(short_evidence) == 1


def test_imported_class_variable_method_call_resolves_and_projects_to_code_edges() -> None:
    """A direct constructor binding can safely navigate a later receiver method call."""
    from service.storage.evidence_store import replace_all_snapshot_parse_results
    from service.storage.sqlite_db import get_connection
    from service.storage.symbol_store import project_symbols_to_code_graph

    repo_id = "receiver-binding-repo"
    snapshot_id = "receiver-binding-snapshot"
    documents = [
        SourceDocument(
            repo_id=repo_id, snapshot_id=snapshot_id, file_id="caller-file", path="caller.py",
            content=(
                "from transport import HTTPAdapter\n\n"
                "class Session:\n"
                "    def send(self, request):\n"
                "        adapter = HTTPAdapter()\n"
                "        return adapter.send(request)\n"
            ),
            language="python",
        ),
        SourceDocument(
            repo_id=repo_id, snapshot_id=snapshot_id, file_id="transport-file", path="transport.py",
            content="class HTTPAdapter:\n    def send(self, request):\n        return request\n",
            language="python",
        ),
    ]
    results = default_registry().parse_all(documents)
    caller = next(item for item in results if item.document.path == "caller.py")
    session_send = next(item for item in caller.symbols if item.qualified_name == "caller.Session.send")
    call = next(
        item for item in caller.relations
        if item.kind == "calls" and item.source_id == session_send.id
        and item.target_qualified_name == "transport.HTTPAdapter.send"
    )

    assert call.target_id is not None
    assert call.resolver_status == "resolved"

    with get_connection() as connection:
        connection.execute(
            "INSERT INTO repos (id, alias, repo_path, status) VALUES (?, ?, ?, 'ready')",
            (repo_id, repo_id, "/tmp/receiver-binding"),
        )
        connection.execute(
            "INSERT INTO repository_snapshots (id, repo_id, commit_hash, status) VALUES (?, ?, ?, 'succeeded')",
            (snapshot_id, repo_id, "b" * 40),
        )
        connection.execute("UPDATE repos SET active_snapshot_id = ? WHERE id = ?", (snapshot_id, repo_id))
        for document in documents:
            connection.execute(
                "INSERT INTO files (id, repo_id, relative_path, snapshot_id) VALUES (?, ?, ?, ?)",
                (document.file_id, repo_id, document.path, snapshot_id),
            )

    replace_all_snapshot_parse_results(
        repo_id,
        snapshot_id,
        [item for result in results for item in result.evidence],
        [item for result in results for item in result.symbols],
        [item for result in results for item in result.relations],
        [item for result in results for item in result.diagnostics],
    )
    project_symbols_to_code_graph(repo_id, snapshot_id)
    with get_connection() as connection:
        edge = connection.execute(
            "SELECT edge_type FROM code_edges WHERE repo_id = ? AND snapshot_id = ? AND source_id = ? AND target_id = ?",
            (repo_id, snapshot_id, call.source_id, call.target_id),
        ).fetchone()
    assert edge[0] == "calls"


def test_receiver_binding_is_cleared_after_reassignment() -> None:
    """A local receiver type must not survive an unrelated reassignment."""
    documents = [
        SourceDocument(
            snapshot_id="snap", path="caller.py",
            content=(
                "from transport import HTTPAdapter\n\n"
                "def send(request, factory):\n"
                "    adapter = HTTPAdapter()\n"
                "    adapter = factory()\n"
                "    return adapter.send(request)\n"
            ),
            language="python",
        ),
        SourceDocument(
            snapshot_id="snap", path="transport.py",
            content="class HTTPAdapter:\n    def send(self, request):\n        return request\n",
            language="python",
        ),
    ]

    caller = next(item for item in default_registry().parse_all(documents) if item.document.path == "caller.py")
    calls = [item for item in caller.relations if item.kind == "calls"]

    assert all(item.target_qualified_name != "transport.HTTPAdapter.send" for item in calls)


def test_actual_mcp_search_wrapper_resolves_to_hybrid_retrieval_entry_point() -> None:
    """真实 MCP 搜索工具应能导航到 HybridRetriever 的实际方法入口。"""
    backend_root = Path(__file__).resolve().parents[1]
    documents = [
        SourceDocument(
            snapshot_id="snap", path=path,
            content=(backend_root / relative_path).read_text(encoding="utf-8"),
            language="python",
        )
        for path, relative_path in [
            ("backend/service/mcp_server/tools.py", "service/mcp_server/tools.py"),
            ("backend/service/core/retrieval/__init__.py", "service/core/retrieval/__init__.py"),
            ("backend/service/core/retrieval/service.py", "service/core/retrieval/service.py"),
        ]
    ]

    mcp_result = next(
        item for item in default_registry().parse_all(documents)
        if item.document.path == "backend/service/mcp_server/tools.py"
    )
    search = next(item for item in mcp_result.symbols if item.name == "search_code")
    retrieval_call = next(
        item for item in mcp_result.relations
        if item.kind == "calls"
        and item.source_id == search.id
        and item.target_qualified_name == "service.core.retrieval.HybridRetriever.retrieve"
    )

    assert retrieval_call.target_id is not None
    assert retrieval_call.resolver_status == "resolved"
    assert retrieval_call.metadata["resolution_method"] == "imported_constructor_method"


def test_source_root_suffix_resolution_stays_unresolved_when_multiple_modules_match() -> None:
    """不同源码根下存在同一导入路径时，不能凭后缀猜测调用目标。"""
    documents = [
        SourceDocument(
            snapshot_id="snap", path="backend/app.py",
            content="from service.worker import run\n\ndef caller():\n    return run()\n",
            language="python",
        ),
        SourceDocument(
            snapshot_id="snap", path="backend/service/worker.py",
            content="def run():\n    return 'backend'\n",
            language="python",
        ),
        SourceDocument(
            snapshot_id="snap", path="tools/service/worker.py",
            content="def run():\n    return 'tools'\n",
            language="python",
        ),
    ]

    caller_result = next(
        item for item in default_registry().parse_all(documents)
        if item.document.path == "backend/app.py"
    )
    call = next(item for item in caller_result.relations if item.kind == "calls")

    assert call.target_qualified_name == "service.worker.run"
    assert call.target_id is None
    assert call.resolver_status == "ambiguous"


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
