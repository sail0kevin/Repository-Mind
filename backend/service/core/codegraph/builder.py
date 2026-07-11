"""
这个文件负责从目录中构建 Python 代码图谱。
它在整个框架里扮演"代码图谱构建层"的角色：扫描源码、解析 AST、抽取函数/类/调用关系，并给出明确的语言支持诊断。
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


@dataclass
class CodeNode:
    """代码图谱中的一个节点。"""

    id: str
    name: str
    node_type: str
    file_path: str
    start_line: int | None = None
    end_line: int | None = None
    signature: str | None = None


@dataclass
class CodeEdge:
    """代码图谱中的一条边。"""

    id: str
    source_id: str
    target_id: str
    edge_type: str


@dataclass
class CodeGraph:
    """代码图谱结果对象。"""

    nodes: list[CodeNode] = field(default_factory=list)
    edges: list[CodeEdge] = field(default_factory=list)
    diagnostics: dict = field(default_factory=dict)


@dataclass
class _FunctionSymbol:
    """临时存放函数定义信息，便于后续匹配调用关系。"""

    node_id: str
    name: str


class CodeGraphBuilder:
    """从目录中构建 Python 代码图谱。"""

    def build_from_directory(self, repo_path) -> CodeGraph:
        """扫描目录并构建 Python 代码图谱。"""
        root = Path(repo_path)
        discovered_sources = list(root.rglob("*.*"))
        python_sources = [path for path in discovered_sources if path.suffix == ".py"]
        diagnostics: dict = {
            "discovered_source_count": len(discovered_sources),
            "supported_python_count": len(python_sources),
            "parsed_count": 0,
            "parse_failures": 0,
            "unsupported_extensions": {
                path.suffix: sum(1 for item in discovered_sources if item.suffix == path.suffix)
                for path in discovered_sources
                if path.suffix != ".py"
            },
            "parse_failure_details": [],
            "status": "succeeded",
            "message": "",
        }
        graph = CodeGraph(diagnostics=diagnostics)
        if not python_sources:
            diagnostics["status"] = "no_supported_sources"
            diagnostics["message"] = "当前仓库没有可解析的 Python 源码文件。"
            return graph
        for python_file in python_sources:
            try:
                self.parse_file(graph, python_file, root)
                diagnostics["parsed_count"] += 1
            except SyntaxError as exc:
                diagnostics["parse_failures"] += 1
                diagnostics["parse_failure_details"].append(
                    {
                        "file": python_file.relative_to(root).as_posix(),
                        "error": str(exc),
                    }
                )
        if diagnostics["parse_failures"] and not graph.nodes:
            diagnostics["status"] = "parse_failed"
            diagnostics["message"] = "所有 Python 文件解析失败。"
        return graph

    def parse_file(self, graph: CodeGraph, python_file: Path, root: Path) -> None:
        """解析单个 Python 文件，追加节点和边。"""
        source = python_file.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(source)
        relative = python_file.relative_to(root).as_posix()
        functions_by_name: dict[str, _FunctionSymbol] = {}
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                node_id = f"class:{relative}:{node.name}"
                graph.nodes.append(
                    CodeNode(
                        id=node_id,
                        name=node.name,
                        node_type="class",
                        file_path=relative,
                        start_line=node.lineno,
                        end_line=getattr(node, "end_lineno", None),
                    )
                )
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                node_id = f"func:{relative}:{node.name}"
                signature = f"def {node.name}(...)"
                graph.nodes.append(
                    CodeNode(
                        id=node_id,
                        name=node.name,
                        node_type="function",
                        file_path=relative,
                        start_line=node.lineno,
                        end_line=getattr(node, "end_lineno", None),
                        signature=signature,
                    )
                )
                functions_by_name[node.name] = _FunctionSymbol(node_id=node_id, name=node.name)
        for func in functions_by_name.values():
            for other in functions_by_name.values():
                if func.node_id == other.node_id:
                    continue
                graph.edges.append(
                    CodeEdge(
                        id=f"call:{func.node_id}->{other.node_id}",
                        source_id=func.node_id,
                        target_id=other.node_id,
                        edge_type="maybe_call",
                    )
                )
