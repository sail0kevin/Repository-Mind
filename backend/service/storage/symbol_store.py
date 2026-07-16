"""M2 Symbol/Relation 查询以及旧 code graph 兼容投影。"""
from __future__ import annotations

import json

from service.storage.evidence_store import list_relations, list_symbols
from service.storage.sqlite_db import get_connection


def project_symbols_to_code_graph(repo_id: str, snapshot_id: str) -> tuple[int, int]:
    """从规范 Symbol/Relation 重建旧节点和边；未解析引用只保留在新关系表。"""
    symbols = list_symbols(repo_id, snapshot_id=snapshot_id, limit=None)
    relations = list_relations(repo_id, snapshot_id=snapshot_id, limit=None)
    known_ids = {item["id"] for item in symbols}
    with get_connection() as connection:
        connection.execute("DELETE FROM code_edges WHERE repo_id = ? AND snapshot_id = ?", (repo_id, snapshot_id))
        connection.execute("DELETE FROM code_nodes WHERE repo_id = ? AND snapshot_id = ?", (repo_id, snapshot_id))
        connection.execute("DELETE FROM code_graph_diagnostics WHERE repo_id = ? AND snapshot_id = ?", (repo_id, snapshot_id))
        for item in symbols:
            connection.execute(
                """INSERT INTO code_nodes (
                       id, repo_id, snapshot_id, name, node_type, file_path, start_line, end_line, signature
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (item["id"], repo_id, snapshot_id, item["name"], item["symbol_kind"], item["file_path"],
                 item["start_line"], item["end_line"], item["signature"]),
            )
        edge_count = 0
        for item in relations:
            source, target = item.get("source_symbol_id"), item.get("target_symbol_id")
            if source not in known_ids or target not in known_ids:
                continue
            connection.execute(
                "INSERT INTO code_edges (id, repo_id, snapshot_id, source_id, target_id, edge_type) VALUES (?, ?, ?, ?, ?, ?)",
                (item["id"], repo_id, snapshot_id, source, target, item["relation_type"]),
            )
            edge_count += 1
        diagnostics = connection.execute(
            "SELECT severity, code, message, file_id, start_line, end_line, parser FROM parser_diagnostics WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchall()
        connection.execute(
            """INSERT INTO code_graph_diagnostics (repo_id, snapshot_id, diagnostics_json, updated_at)
               VALUES (?, ?, ?, CURRENT_TIMESTAMP)""",
            (repo_id, snapshot_id, json.dumps([dict(row) for row in diagnostics], ensure_ascii=False)),
        )
    return len(symbols), edge_count


__all__ = ["list_symbols", "list_relations", "project_symbols_to_code_graph"]
