"""M3 Repository Catalog 的快照隔离持久化与树查询。"""
from __future__ import annotations

import json
from typing import Iterable

from service.core.catalog.models import CatalogItem
from service.storage.sqlite_db import get_connection


def replace_snapshot_catalog(repo_id: str, snapshot_id: str, items: Iterable[CatalogItem]) -> int:
    """原子替换单个快照 Catalog，拒绝跨仓库或跨快照卡片。"""
    item_list = list(items)
    # 自引用外键要求父节点先写入；同层再按稳定 ID 排序，保证重复构建结果一致。
    rank = {"repository_overview": 0, "subsystem": 1, "directory": 2, "file": 3, "symbol": 4, "reading_guide": 5}
    item_list.sort(key=lambda item: (rank.get(item.kind, 99), item.id))
    with get_connection() as connection:
        snapshot = connection.execute(
            "SELECT id FROM repository_snapshots WHERE id = ? AND repo_id = ?", (snapshot_id, repo_id)
        ).fetchone()
        if snapshot is None:
            raise ValueError("快照不存在或不属于指定仓库")
        connection.execute("DELETE FROM catalog_items WHERE repo_id = ? AND snapshot_id = ?", (repo_id, snapshot_id))
        for item in item_list:
            if item.repo_id != repo_id or item.snapshot_id != snapshot_id:
                raise ValueError("Catalog 卡片必须属于当前仓库快照")
            connection.execute(
                """INSERT INTO catalog_items (
                       id, repo_id, snapshot_id, kind, title, path, parent_id, summary, details_json,
                       generation_method, model, prompt_version, token_count, source_evidence_ids_json,
                       freshness, known_unknowns_json
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (item.id, repo_id, snapshot_id, item.kind, item.title, item.path, item.parent_id, item.summary,
                 json.dumps(item.details, ensure_ascii=False, sort_keys=True), item.generation_method, item.model,
                 item.prompt_version, item.token_count, json.dumps(list(item.source_evidence_ids), ensure_ascii=False),
                 item.freshness, json.dumps(list(item.known_unknowns), ensure_ascii=False)),
            )
    return len(item_list)


def _decode(row) -> dict:
    item = dict(row)
    item["details"] = json.loads(item.pop("details_json") or "{}")
    item["source_evidence_ids"] = json.loads(item.pop("source_evidence_ids_json") or "[]")
    item["known_unknowns"] = json.loads(item.pop("known_unknowns_json") or "[]")
    return item


def list_catalog_items(repo_id: str, snapshot_id: str, kind: str | None = None) -> list[dict]:
    """列出一个成功快照中的 Catalog 卡片。"""
    with get_connection() as connection:
        params: list[object] = [repo_id, snapshot_id]
        where = "repo_id = ? AND snapshot_id = ?"
        if kind:
            where += " AND kind = ?"
            params.append(kind)
        rows = connection.execute(
            f"SELECT * FROM catalog_items WHERE {where} ORDER BY kind, path, title, id", params
        ).fetchall()
    return [_decode(row) for row in rows]


def get_catalog_item(repo_id: str, snapshot_id: str, item_id: str) -> dict | None:
    """按仓库和快照读取详情，避免相同 ID 被跨快照访问。"""
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM catalog_items WHERE repo_id = ? AND snapshot_id = ? AND id = ?",
            (repo_id, snapshot_id, item_id),
        ).fetchone()
    return _decode(row) if row else None


def get_catalog_tree(repo_id: str, snapshot_id: str) -> list[dict]:
    """把平面卡片转换为 overview→subsystem→directory→file→symbol 的树。"""
    items = list_catalog_items(repo_id, snapshot_id)
    nodes = {item["id"]: {**item, "children": []} for item in items}
    roots: list[dict] = []
    for item in items:
        node = nodes[item["id"]]
        parent = nodes.get(item.get("parent_id"))
        if parent is None:
            roots.append(node)
        else:
            parent["children"].append(node)
    return roots
