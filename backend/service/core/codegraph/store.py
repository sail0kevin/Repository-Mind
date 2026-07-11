"""
这个文件负责代码图谱的持久化读写。
它在整个框架里扮演"图谱存储层"的角色：把节点、边和诊断信息一起写进 SQLite，并覆盖旧数据。
"""
from __future__ import annotations

import json

from service.storage.sqlite_db import get_connection


def save_graph(repo_id: str, graph) -> None:
    """保存代码图谱，包括节点、边和诊断信息。"""
    nodes = [
        {
            "id": getattr(node, "id", f"node_{index}"),
            "name": getattr(node, "name", ""),
            "node_type": getattr(node, "node_type", ""),
            "file_path": getattr(node, "file_path", ""),
            "start_line": getattr(node, "start_line", None),
            "end_line": getattr(node, "end_line", None),
            "signature": getattr(node, "signature", None),
        }
        for index, node in enumerate(graph.nodes)
    ]
    edges = [
        {
            "id": getattr(edge, "id", f"edge_{index}"),
            "source_id": getattr(edge, "source_id", ""),
            "target_id": getattr(edge, "target_id", ""),
            "edge_type": getattr(edge, "edge_type", ""),
        }
        for index, edge in enumerate(graph.edges)
    ]
    diagnostics = getattr(graph, "diagnostics", {}) or {}
    with get_connection() as connection:
        connection.execute("DELETE FROM code_nodes WHERE repo_id = ?", (repo_id,))
        connection.execute("DELETE FROM code_edges WHERE repo_id = ?", (repo_id,))
        connection.execute(
            "DELETE FROM code_graph_diagnostics WHERE repo_id = ?",
            (repo_id,),
        )
        for node in nodes:
            connection.execute(
                """
                INSERT INTO code_nodes (id, repo_id, name, node_type, file_path, start_line, end_line, signature)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    node["id"],
                    repo_id,
                    node["name"],
                    node["node_type"],
                    node["file_path"],
                    node["start_line"],
                    node["end_line"],
                    node["signature"],
                ),
            )
        for edge in edges:
            connection.execute(
                """
                INSERT INTO code_edges (id, repo_id, source_id, target_id, edge_type)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    edge["id"],
                    repo_id,
                    edge["source_id"],
                    edge["target_id"],
                    edge["edge_type"],
                ),
            )
        connection.execute(
            """
            INSERT INTO code_graph_diagnostics (repo_id, diagnostics_json, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(repo_id) DO UPDATE SET
                diagnostics_json = excluded.diagnostics_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (repo_id, json.dumps(diagnostics, ensure_ascii=False)),
        )


def get_graph_stats(repo_id: str) -> dict:
    """读取图谱统计信息。"""
    with get_connection() as connection:
        node_count = connection.execute(
            "SELECT COUNT(*) AS total FROM code_nodes WHERE repo_id = ?",
            (repo_id,),
        ).fetchone()["total"]
        edge_count = connection.execute(
            "SELECT COUNT(*) AS total FROM code_edges WHERE repo_id = ?",
            (repo_id,),
        ).fetchone()["total"]
        row = connection.execute(
            "SELECT diagnostics_json FROM code_graph_diagnostics WHERE repo_id = ?",
            (repo_id,),
        ).fetchone()
    diagnostics = json.loads(row["diagnostics_json"]) if row and row["diagnostics_json"] else {}
    return {
        "total_nodes": node_count,
        "total_edges": edge_count,
        "functions": 0,
        "classes": 0,
        "files_analyzed": 0,
        "diagnostics": diagnostics,
    }
