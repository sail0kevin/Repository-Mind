"""
这个文件负责代码图谱的持久化读写。
它在整个框架里扮演“图谱存储层”的角色：保存节点、边和诊断信息，并提供稳定的查询能力。
"""
from __future__ import annotations

import hashlib
import json
from collections import deque

from service.storage.sqlite_db import get_connection


def _selected_snapshot(connection, repo_id: str, snapshot_id: str | None) -> str | None:
    if snapshot_id is not None:
        row = connection.execute("SELECT id FROM repository_snapshots WHERE id = ? AND repo_id = ?", (snapshot_id, repo_id)).fetchone()
        if row is None:
            raise ValueError("快照不存在或不属于指定仓库")
        return snapshot_id
    row = connection.execute("SELECT active_snapshot_id FROM repos WHERE id = ?", (repo_id,)).fetchone()
    return row["active_snapshot_id"] if row else None


def save_graph(repo_id: str, graph, snapshot_id: str | None = None) -> None:
    """保存指定快照的代码图谱，包括节点、边和诊断信息。"""
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
        selected = snapshot_id
        if selected is None:
            repo = connection.execute("SELECT active_snapshot_id FROM repos WHERE id = ?", (repo_id,)).fetchone()
            selected = repo["active_snapshot_id"] if repo else None
        # 图谱 builder 的节点 ID 对同一代码稳定，但不同快照需要命名空间隔离，避免主键冲突。
        id_map = {}
        for node in nodes:
            identity = f"{repo_id}\0{selected}\0{node['id']}"
            id_map[node["id"]] = f"node_{hashlib.sha256(identity.encode()).hexdigest()[:32]}"
        for node in nodes:
            node["id"] = id_map[node["id"]]
        for edge in edges:
            original_id = edge["id"]
            edge["id"] = f"edge_{hashlib.sha256(f'{repo_id}\0{selected}\0{original_id}'.encode()).hexdigest()[:32]}"
            edge["source_id"] = id_map.get(edge["source_id"], edge["source_id"])
            edge["target_id"] = id_map.get(edge["target_id"], edge["target_id"])
        connection.execute("DELETE FROM code_nodes WHERE repo_id = ? AND snapshot_id IS ?", (repo_id, selected))
        connection.execute("DELETE FROM code_edges WHERE repo_id = ? AND snapshot_id IS ?", (repo_id, selected))
        connection.execute("DELETE FROM code_graph_diagnostics WHERE repo_id = ? AND snapshot_id IS ?", (repo_id, selected))
        for node in nodes:
            connection.execute(
                """
                INSERT INTO code_nodes (id, repo_id, snapshot_id, name, node_type, file_path, start_line, end_line, signature)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    node["id"], repo_id, selected, node["name"], node["node_type"], node["file_path"],
                    node["start_line"], node["end_line"], node["signature"],
                ),
            )
        for edge in edges:
            connection.execute(
                """
                INSERT INTO code_edges (id, repo_id, snapshot_id, source_id, target_id, edge_type)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (edge["id"], repo_id, selected, edge["source_id"], edge["target_id"], edge["edge_type"]),
            )
        connection.execute(
            """
            INSERT INTO code_graph_diagnostics (repo_id, snapshot_id, diagnostics_json, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (repo_id, selected, json.dumps(diagnostics, ensure_ascii=False)),
        )


def get_graph_stats(repo_id: str, snapshot_id: str | None = None) -> dict:
    with get_connection() as connection:
        selected = _selected_snapshot(connection, repo_id, snapshot_id)
        counts = connection.execute("""SELECT COUNT(*) AS total_nodes, SUM(CASE WHEN node_type='function' THEN 1 ELSE 0 END) AS functions, SUM(CASE WHEN node_type='class' THEN 1 ELSE 0 END) AS classes, COUNT(DISTINCT file_path) AS files_analyzed FROM code_nodes WHERE repo_id=? AND snapshot_id IS ?""", (repo_id, selected)).fetchone()
        edge_count = connection.execute("SELECT COUNT(*) AS total FROM code_edges WHERE repo_id=? AND snapshot_id IS ?", (repo_id, selected)).fetchone()["total"]
        row = connection.execute("SELECT diagnostics_json FROM code_graph_diagnostics WHERE repo_id=? AND snapshot_id IS ?", (repo_id, selected)).fetchone()
    diagnostics = json.loads(row["diagnostics_json"]) if row and row["diagnostics_json"] else {}
    return {"repo_id": repo_id, "total_nodes": counts["total_nodes"], "total_edges": edge_count, "functions": counts["functions"] or 0, "classes": counts["classes"] or 0, "files_analyzed": counts["files_analyzed"] or 0, "diagnostics": diagnostics}


def _node_from_row(row, importance: int = 0) -> dict:
    return {"id": row["id"], "name": row["name"] or "", "node_type": row["node_type"] or "", "file_path": row["file_path"] or "", "start_line": row["start_line"], "end_line": row["end_line"], "signature": row["signature"], "importance": importance}


def search_graph_nodes(repo_id: str, query: str, limit: int = 20, node_type: str | None = None, snapshot_id: str | None = None) -> list[dict]:
    pattern = f"%{query.strip()}%"
    with get_connection() as connection:
        selected = _selected_snapshot(connection, repo_id, snapshot_id)
        clauses = ["repo_id = ?", "snapshot_id IS ?", "(name LIKE ? OR signature LIKE ? OR file_path LIKE ?)"]
        params: list[object] = [repo_id, selected, pattern, pattern, pattern]
        if node_type:
            clauses.append("node_type = ?"); params.append(node_type)
        params.append(max(1, min(limit, 100)))
        rows = connection.execute(f"SELECT * FROM code_nodes WHERE {' AND '.join(clauses)} ORDER BY name, file_path LIMIT ?", params).fetchall()
    return [_node_from_row(row) for row in rows]


def get_important_nodes(repo_id: str, limit: int = 20, snapshot_id: str | None = None) -> list[dict]:
    with get_connection() as connection:
        selected = _selected_snapshot(connection, repo_id, snapshot_id)
        rows = connection.execute("""SELECT n.*, COUNT(e.id) AS importance FROM code_nodes n LEFT JOIN code_edges e ON e.repo_id=n.repo_id AND e.snapshot_id IS n.snapshot_id AND (e.source_id=n.id OR e.target_id=n.id) WHERE n.repo_id=? AND n.snapshot_id IS ? GROUP BY n.id ORDER BY importance DESC, n.name ASC LIMIT ?""", (repo_id, selected, max(1, min(limit, 100)))).fetchall()
    return [_node_from_row(row, row["importance"]) for row in rows]


def get_call_chain(repo_id: str, symbol: str, direction: str, depth: int, snapshot_id: str | None = None) -> dict:
    matches = search_graph_nodes(repo_id, symbol, 1, "function", snapshot_id)
    if not matches: return {"root": None, "nodes": [], "edges": []}
    root, max_depth = matches[0], max(1, min(depth, 10))
    with get_connection() as connection:
        selected = _selected_snapshot(connection, repo_id, snapshot_id)
        node_rows = connection.execute("SELECT * FROM code_nodes WHERE repo_id=? AND snapshot_id IS ?", (repo_id, selected)).fetchall()
        edge_rows = connection.execute("SELECT * FROM code_edges WHERE repo_id=? AND snapshot_id IS ?", (repo_id, selected)).fetchall()
    nodes_by_id = {row["id"]: _node_from_row(row) for row in node_rows}; queue=deque([(root["id"],0)]); visited={root["id"]}; result_edges=[]
    while queue:
        node_id,current_depth=queue.popleft()
        if current_depth >= max_depth: continue
        for edge in edge_rows:
            next_id = edge["target_id"] if direction in ("callees","both") and edge["source_id"]==node_id else edge["source_id"] if direction in ("callers","both") and edge["target_id"]==node_id else None
            if next_id is None or next_id not in nodes_by_id: continue
            result_edges.append({"source_id":edge["source_id"],"target_id":edge["target_id"],"edge_type":edge["edge_type"] or "","depth":current_depth+1})
            if next_id not in visited: visited.add(next_id); queue.append((next_id,current_depth+1))
    return {"root":root,"nodes":[nodes_by_id[x] for x in visited],"edges":result_edges}


def get_class_relations(repo_id: str, class_name: str, snapshot_id: str | None = None) -> dict:
    matches=search_graph_nodes(repo_id,class_name,1,"class",snapshot_id)
    if not matches: return {"class_node":None,"related_nodes":[],"relations":[]}
    class_node=matches[0]
    with get_connection() as connection:
        selected=_selected_snapshot(connection,repo_id,snapshot_id)
        edges=connection.execute("SELECT * FROM code_edges WHERE repo_id=? AND snapshot_id IS ? AND (source_id=? OR target_id=?)",(repo_id,selected,class_node["id"],class_node["id"])).fetchall()
        related_ids={e["target_id"] if e["source_id"]==class_node["id"] else e["source_id"] for e in edges}; related_rows=[]
        if related_ids:
            placeholders=",".join("?" for _ in related_ids)
            related_rows=connection.execute(f"SELECT * FROM code_nodes WHERE repo_id=? AND snapshot_id IS ? AND id IN ({placeholders})",[repo_id,selected,*related_ids]).fetchall()
    relations=[{"source_id":e["source_id"],"target_id":e["target_id"],"edge_type":e["edge_type"] or "","depth":1} for e in edges]
    return {"class_node":class_node,"related_nodes":[_node_from_row(r) for r in related_rows],"relations":relations}
