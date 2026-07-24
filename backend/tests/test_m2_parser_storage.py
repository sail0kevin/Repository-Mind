"""M2 统一解析模型、linker、v004 与 canonical stores 验收测试。"""
from __future__ import annotations

from dataclasses import replace
import sqlite3

import pytest

from service.core.parsing.config_adapter import ConfigParser
from service.core.parsing.javascript_typescript_parser import JavaScriptTypeScriptParser
from service.core.parsing.models import Diagnostic, EvidenceUnit, ParseResult, Relation, SourceDocument, Symbol
from service.core.parsing.linker import RepositoryLinker
from service.core.parsing.registry import default_registry
from service.storage.evidence_store import (
    get_evidence_unit,
    list_evidence_units,
    list_parser_diagnostics,
    list_relations,
    list_symbols,
    project_evidence_to_chunks,
    replace_all_snapshot_parse_results,
    replace_snapshot_parse_results,
)
from service.storage.sqlite_db import get_connection
from service.storage.symbol_store import project_symbols_to_code_graph


def _seed(repo_id: str = "repo", snapshot_id: str = "snap", file_ids: tuple[str, ...] = ("file-a",)) -> None:
    """建立 stores 测试所需的最小仓库、快照和文件记录。"""
    with get_connection() as connection:
        # active_snapshot_id 有外键约束，因此先创建仓库，再创建快照，最后激活快照。
        connection.execute(
            "INSERT INTO repos (id, alias, repo_path, status) VALUES (?, ?, ?, 'ready')",
            (repo_id, repo_id, "/tmp/repo"),
        )
        connection.execute(
            "INSERT INTO repository_snapshots (id, repo_id, commit_hash, status) VALUES (?, ?, ?, 'succeeded')",
            (snapshot_id, repo_id, "a" * 40),
        )
        connection.execute(
            "UPDATE repos SET active_snapshot_id = ? WHERE id = ?",
            (snapshot_id, repo_id),
        )
        for index, file_id in enumerate(file_ids):
            connection.execute(
                "INSERT INTO files (id, repo_id, relative_path, snapshot_id) VALUES (?, ?, ?, ?)",
                (file_id, repo_id, f"src/f{index}.py", snapshot_id),
            )


def _python_result(file_id: str = "file-a", snapshot_id: str = "snap"):
    """生成带 file_id 的规范 Python 解析结果。"""
    document = SourceDocument(
        repo_id="repo", snapshot_id=snapshot_id, file_id=file_id, path="src/f.py",
        content="def hello(name: str):\r\n    return name + '😀'\r\n", language="python",
    )
    return default_registry().parse(document)


def test_unicode_crlf_utf16_and_logical_ids_are_stable() -> None:
    """Unicode/emoji/CRLF/UTF-16 原始字节和两类 ID 必须具有明确语义。"""
    text = "# 标题😀\r\ndef run():\r\n    return '好'\r\n"
    first = SourceDocument(snapshot_id="s1", path="src/中文.py", content=text, language="python")
    second = SourceDocument(snapshot_id="s2", path="src/中文.py", content=text.replace("好", "很好"), language="python")
    encoded = text.encode("utf-16")
    utf16 = SourceDocument(snapshot_id="s1", path="notes.txt", content=text, raw_bytes=encoded, encoding="utf-16")
    first_result = default_registry().parse(first)
    second_result = default_registry().parse(second)
    first_run = next(item for item in first_result.symbols if item.name == "run")
    second_run = next(item for item in second_result.symbols if item.name == "run")

    assert first.newline_style == "\r\n"
    assert utf16.raw_bytes == encoded
    assert first_run.logical_id == second_run.logical_id
    assert first_run.id != second_run.id
    assert "好" in next(item.content for item in first_result.evidence if item.symbol_id == first_run.id)


def test_repository_linker_does_not_connect_ambiguous_short_names() -> None:
    """两个同名候选存在时，裸调用只能保留 target_ref 和歧义诊断。"""
    documents = [
        SourceDocument(snapshot_id="s", path="a.py", content="def duplicate():\n    pass\n", language="python"),
        SourceDocument(snapshot_id="s", path="b.py", content="def duplicate():\n    pass\n", language="python"),
        SourceDocument(snapshot_id="s", path="caller.py", content="def run():\n    duplicate()\n", language="python"),
    ]
    result = default_registry().parse_all(documents)[2]
    calls = [item for item in result.relations if item.kind == "calls"]

    # Python 局部解析器没有可证明绑定时不会凭短名称制造调用边。
    assert calls == []
    assert all(item.kind != "maybe_call" for item in result.relations)


def test_config_parser_and_tree_sitter_fallback_are_honest(monkeypatch: pytest.MonkeyPatch) -> None:
    """配置错误和 grammar 缺失都应显式 fallback，不伪造结构。"""
    broken = ConfigParser().parse(SourceDocument(snapshot_id="s", path="x.json", content="{", language="json"))
    assert broken.status == "fallback_text"
    assert broken.diagnostics[0].code == "config_parse_error"

    import service.core.parsing.javascript_typescript_parser as module
    monkeypatch.setattr(module, "_TREE_SITTER_IMPORT_ERROR", ImportError("missing grammar"))
    fallback = JavaScriptTypeScriptParser().parse(
        SourceDocument(snapshot_id="s", path="x.ts", content="export const x = 1", language="typescript")
    )
    assert fallback.status == "fallback_text"
    assert not fallback.symbols and not fallback.relations
    assert fallback.diagnostics[0].code == "tree_sitter_unavailable"


def test_config_parser_handles_yaml_boolean_keys_like_github_workflow_on() -> None:
    """YAML 1.1 把裸 on/off/yes/no 解析成布尔值；GitHub Actions workflow 几乎都有顶层 `on:`。

    回归背景：`json.dumps(..., sort_keys=True)` 遇到同一个 dict 里混有 str 和
    bool 类型的 key 时会抛 `TypeError: '<' not supported between instances of
    'bool' and 'str'`，导致这类文件被判定为 status="failed"，进而让整个仓库
    ingest 被拒绝发布（`解析器内部失败，拒绝发布`）。
    """
    content = "name: CI\non:\n  push:\n    branches: [main]\njobs:\n  build:\n    runs-on: ubuntu-latest\n"
    result = ConfigParser().parse(
        SourceDocument(snapshot_id="s", path=".github/workflows/ci.yml", content=content, language="yaml")
    )
    assert result.status == "parsed"
    assert not result.diagnostics


def test_v004_constraints_and_single_file_transaction_rollback() -> None:
    """v004 的非空/唯一约束必须生效，replace 冲突必须完整回滚。"""
    _seed()
    result = _python_result()
    replace_snapshot_parse_results("repo", "snap", "file-a", result.evidence, result.symbols, result.relations, [])
    before = list_evidence_units("repo", "snap", limit=1000)
    duplicate = replace(result.evidence[0], id="different-record")

    with pytest.raises(sqlite3.IntegrityError):
        replace_snapshot_parse_results("repo", "snap", "file-a", [result.evidence[0], duplicate], [], [], [])

    assert list_evidence_units("repo", "snap", limit=1000) == before
    with get_connection() as connection:
        columns = {row[1]: row[3] for row in connection.execute("PRAGMA table_info(evidence_units)")}
        assert columns["logical_id"] == 1
        assert columns["identity_key"] == 1
        sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='relations'"
        ).fetchone()[0]
        assert "observation_state" not in sql
        assert "resolver_status" in sql and "observed" in sql and "inferred" in sql


def test_snapshot_replace_queries_diagnostics_and_projections_are_scoped() -> None:
    """全快照 replace、查询和旧 chunks/codegraph 投影必须保持 snapshot scope。"""
    _seed(file_ids=("file-a", "file-b"))
    result = _python_result()
    diagnostic = Diagnostic(
        code="demo", message="测试诊断", severity="warning", path=result.document.path,
        parser="python-ast", snapshot_id="snap", file_id="file-a",
    )
    counts = replace_all_snapshot_parse_results(
        "repo", "snap", result.evidence, result.symbols, result.relations, [diagnostic]
    )

    assert counts["symbols"] == len(result.symbols)
    assert list_symbols("repo", "snap", query="hello")
    assert list_relations("repo", "snap")
    assert list_parser_diagnostics("repo", "snap")[0]["code"] == "demo"
    evidence = list_evidence_units("repo", "snap", query="hello")
    assert evidence and get_evidence_unit("repo", evidence[0]["id"], "snap")
    assert project_evidence_to_chunks("repo", "snap") == len(result.evidence)
    node_count, edge_count = project_symbols_to_code_graph("repo", "snap")
    assert node_count == len(result.symbols)
    assert edge_count <= len(result.relations)



def test_python_import_aliases_have_distinct_stable_evidence_ids() -> None:
    """同一 import 语句的每个 alias 必须拥有稳定且不冲突的结构身份。"""
    source = "import os, sys\nfrom pkg import item as first, item as second\n"
    first = default_registry().parse(SourceDocument(snapshot_id="s1", path="imports.py", content=source, language="python"))
    second = default_registry().parse(SourceDocument(snapshot_id="s2", path="imports.py", content=source, language="python"))
    left = [item for item in first.evidence if item.kind == "relation:imports"]
    right = [item for item in second.evidence if item.kind == "relation:imports"]
    assert len(left) == len({item.id for item in left}) == 4
    assert [item.logical_id for item in left] == [item.logical_id for item in right]


def test_unimported_unique_bare_name_is_not_linked_across_files() -> None:
    """全仓唯一裸名也不能越过文件作用域凭猜测绑定。"""
    documents = [
        SourceDocument(snapshot_id="s", path="base.py", content="class Base:\n    pass\n", language="python"),
        SourceDocument(snapshot_id="s", path="child.ts", content="class Child extends Base {}", language="typescript"),
    ]
    result = default_registry().parse_all(documents)[1]
    inheritance = next(item for item in result.relations if item.kind == "inherits")
    assert inheritance.target_id is None
    assert inheritance.resolver_status == "unresolved"


def test_duplicate_symbol_definitions_are_distinct_and_persistable() -> None:
    """同名重定义不能共享逻辑/记录身份，也不能被 qualified_name 唯一约束拒绝。"""
    _seed()
    document = SourceDocument(repo_id="repo", snapshot_id="snap", file_id="file-a", path="src/f.py",
                              content="def same(x):\n    return x\n\ndef same(x, y):\n    return x + y\n", language="python")
    result = default_registry().parse(document)
    definitions = [item for item in result.symbols if item.name == "same"]
    assert len(definitions) == 2
    assert len({item.id for item in definitions}) == len({item.logical_id for item in definitions}) == 2
    replace_all_snapshot_parse_results("repo", "snap", result.evidence, result.symbols, result.relations, result.diagnostics)
    assert len([item for item in list_symbols("repo", "snap") if item["name"] == "same"]) == 2


def test_repeated_js_ts_export_call_and_heritage_evidence_have_distinct_identity_and_are_persistable() -> None:
    """同一模块/符号下的多条 export、call、heritage 证据不能共享 logical_id。

    回归背景：`_add_exports`/`_add_heritage`/`_add_calls` 原先都不传 `identity`，
    这类证据的 structural_identity 会回退到裸 kind 字符串。同一模块内出现第二个
    export 语句、同一函数内出现第二次直接调用、或同一符号有多条 heritage 目标时，
    第二条证据会和第一条拥有完全相同的 logical_id，撞上 evidence_units 的
    UNIQUE(snapshot_id, identity_key) 约束，导致整个仓库 ingest 被拒绝发布。
    """
    _seed()
    document = SourceDocument(
        repo_id="repo", snapshot_id="snap", file_id="file-a", path="src/f.ts",
        content=(
            "export const a = 1;\n"
            "export const b = 2;\n"
            "\n"
            "function run() {\n"
            "  foo();\n"
            "  bar();\n"
            "}\n"
            "\n"
            "class C implements A, B {}\n"
        ),
        language="typescript",
    )
    result = JavaScriptTypeScriptParser().parse(document)
    if result.status == "fallback_text":
        assert result.diagnostics[0].code == "tree_sitter_unavailable"
        return

    exports = [item for item in result.evidence if item.kind == "export"]
    calls = [item for item in result.evidence if item.kind == "call"]
    heritage = [item for item in result.evidence if item.kind == "relation"]
    assert len(exports) == 2 and len({item.logical_id for item in exports}) == 2
    assert len(calls) == 2 and len({item.logical_id for item in calls}) == 2
    assert len(heritage) == 2 and len({item.logical_id for item in heritage}) == 2

    replace_all_snapshot_parse_results("repo", "snap", result.evidence, result.symbols, result.relations, result.diagnostics)
    assert len(list_evidence_units("repo", "snap")) == len(result.evidence)


def test_python_syntax_error_is_publishable_fallback_but_internal_failure_is_not() -> None:
    """用户语法错误应保留诊断与文本，适配器异常仍是 failed。"""
    broken = default_registry().parse_all([
        SourceDocument(snapshot_id="s", path="broken.py", content="def nope(:\n", language="python")
    ])[0]
    assert broken.status == "parsed_with_errors"
    assert broken.evidence and broken.diagnostics[0].code == "python_syntax_error"

    from service.core.parsing.base import ParserAdapter
    from service.core.parsing.registry import ParserRegistry
    class Exploding(ParserAdapter):
        languages = frozenset({"python"})
        extensions = frozenset({".py"})
        def parse(self, document):
            raise RuntimeError("internal")
    failed = ParserRegistry([Exploding()]).parse_all([
        SourceDocument(snapshot_id="s", path="ok.py", content="pass", language="python")
    ])[0]
    assert failed.status == "failed"
    assert failed.diagnostics[0].code == "parser_failed"


def test_js_relative_imports_resolve_extensions_and_index_without_ambiguous_overwrite() -> None:
    """JS 相对 import 支持扩展/index；Python 模块歧义必须保留 ambiguous。"""
    foo_doc = SourceDocument(snapshot_id="s", path="src/foo.ts", content="")
    pkg_doc = SourceDocument(snapshot_id="s", path="src/pkg/index.tsx", content="")
    main_doc = SourceDocument(snapshot_id="s", path="src/main.ts", content="")
    foo = Symbol.create(foo_doc, name="foo.ts", qualified_name="src/foo.ts", kind="module", start_line=1, end_line=1)
    pkg = Symbol.create(pkg_doc, name="index.tsx", qualified_name="src/pkg/index.tsx", kind="module", start_line=1, end_line=1)
    main = Symbol.create(main_doc, name="main.ts", qualified_name="src/main.ts", kind="module", start_line=1, end_line=1)
    evidence = [EvidenceUnit.create(main_doc, index, index, kind="import", content=target, identity=(target, index))
                for index, target in enumerate(("./foo", "./pkg"), start=1)]
    relations = [Relation.create(main_doc, kind="imports", source_id=main.id, target_id=None, target_ref=target,
        observed=True, inferred=False, confidence=1.0, evidence_id=evidence[index].id, line=index + 1)
        for index, target in enumerate(("./foo", "./pkg"))]
    result = RepositoryLinker().link([ParseResult(foo_doc, symbols=[foo]), ParseResult(pkg_doc, symbols=[pkg]),
                                      ParseResult(main_doc, symbols=[main], evidence=evidence, relations=relations)])[2]
    assert len(result.relations) == 2 and all(item.target_id for item in result.relations)

    ambiguous = default_registry().parse_all([
        SourceDocument(snapshot_id="s", path="pkg.py", content="pass", language="python"),
        SourceDocument(snapshot_id="s", path="pkg/__init__.py", content="pass", language="python"),
        SourceDocument(snapshot_id="s", path="use.py", content="import pkg\n", language="python"),
    ])[2]
    relation = next(item for item in ambiguous.relations if item.kind == "imports")
    assert relation.target_id is None and relation.resolver_status == "ambiguous"


def test_source_document_path_normalization_preserves_dot_names_and_rejects_escape() -> None:
    """路径规范化只去精确 ./，并拒绝绝对路径与仓库根逃逸。"""
    assert SourceDocument(snapshot_id="s", path="./.github/workflows/a.yml", content="").path == ".github/workflows/a.yml"
    with pytest.raises(ValueError):
        SourceDocument(snapshot_id="s", path="../secret.py", content="")
    with pytest.raises(ValueError):
        SourceDocument(snapshot_id="s", path="/absolute.py", content="")


def test_ranges_are_persisted_and_evidence_logical_id_survives_line_shift() -> None:
    """DB 保留列位置/关系位置，结构证据整体下移时 logical_id 不变。"""
    _seed()
    first = default_registry().parse(SourceDocument(repo_id="repo", snapshot_id="snap", file_id="file-a",
        path="src/f.py", content="def run():\n    return 1\n", language="python"))
    shifted = default_registry().parse(SourceDocument(repo_id="repo", snapshot_id="other", file_id="file-a",
        path="src/f.py", content="\n\ndef run():\n    return 1\n", language="python"))
    first_run = next(item for item in first.evidence if item.kind == "function")
    shifted_run = next(item for item in shifted.evidence if item.kind == "function")
    assert first_run.logical_id == shifted_run.logical_id and first_run.id != shifted_run.id
    replace_all_snapshot_parse_results("repo", "snap", first.evidence, first.symbols, first.relations, first.diagnostics)
    with get_connection() as connection:
        evidence = connection.execute("SELECT start_column, end_column FROM evidence_units WHERE id = ?", (first_run.id,)).fetchone()
        relation = connection.execute("SELECT line, column FROM relations WHERE snapshot_id = ? LIMIT 1", ("snap",)).fetchone()
    assert evidence[0] == 0 and evidence[1] >= 0
    assert relation[0] >= 1 and relation[1] >= 0


def test_config_position_index_is_built_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """配置节点定位应复用一次预建索引，而不是逐节点扫描全部行。"""
    calls = 0
    original = ConfigParser._build_position_index
    def counted(lines):
        nonlocal calls
        calls += 1
        return original(lines)
    monkeypatch.setattr(ConfigParser, "_build_position_index", staticmethod(counted))
    content = "{\n" + ",\n".join(f'  \"key{i}\": {i}' for i in range(100)) + "\n}"
    result = ConfigParser().parse(SourceDocument(snapshot_id="s", path="x.json", content=content, language="json"))
    assert result.status == "parsed" and calls == 1 and len(result.evidence) == 101
