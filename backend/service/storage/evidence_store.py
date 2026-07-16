"""
这个文件负责 M2 Evidence 事实源的持久化和查询。
写入时统一校验快照归属；旧 chunks 只是 Evidence 的兼容投影，不再是新快照事实源。
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

from service.storage.sqlite_db import get_connection
from service.storage.lexical_store import replace_snapshot_fts_rows


def _value(item: Any, name: str, default=None):
    """同时读取 dataclass/Pydantic 对象和字典，避免存储层绑定具体解析模型实现。"""
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _json(value: Any) -> str | None:
    """把解析器元数据稳定编码为 JSON。"""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _first(item: Any, *names: str, default=None):
    """按多个兼容字段名读取同一个语义值。"""
    for name in names:
        value = _value(item, name)
        if value is not None:
            return value
    return default


def _metadata(item: Any) -> dict[str, Any]:
    value = _value(item, "metadata")
    return value if isinstance(value, dict) else {}


def _selected_snapshot(connection, repo_id: str, snapshot_id: str | None) -> str | None:
    """显式快照必须属于仓库；未显式指定时读取 active 快照。"""
    if snapshot_id is not None:
        row = connection.execute(
            "SELECT id FROM repository_snapshots WHERE id = ? AND repo_id = ?", (snapshot_id, repo_id)
        ).fetchone()
        if row is None:
            raise ValueError("快照不存在或不属于指定仓库")
        return snapshot_id
    row = connection.execute("SELECT active_snapshot_id FROM repos WHERE id = ?", (repo_id,)).fetchone()
    return row["active_snapshot_id"] if row else None



def _insert_parse_facts(connection, repo_id: str, snapshot_id: str, evidence_list: list[Any],
                        symbol_list: list[Any], relation_list: list[Any], diagnostic_list: list[Any],
                        expected_file_id: str | None) -> None:
    """在调用方事务内写入一批规范事实，不吞掉唯一约束或外键冲突。"""
    valid_files = {str(row["id"]) for row in connection.execute(
        "SELECT id FROM files WHERE repo_id = ? AND snapshot_id = ?", (repo_id, snapshot_id)
    ).fetchall()}

    def checked_file(item: Any) -> str:
        file_id = str(_value(item, "file_id") or "")
        if not file_id or file_id not in valid_files:
            raise ValueError("解析事实的 file_id 不属于当前快照")
        if expected_file_id is not None and file_id != expected_file_id:
            raise ValueError("解析事实必须属于当前文件")
        return file_id

    # parent_id 使用复合外键，因此必须先写父 Evidence。
    pending = {str(_value(item, "id")): item for item in evidence_list}
    while pending:
        inserted = 0
        for evidence_id, item in list(pending.items()):
            if str(_value(item, "snapshot_id")) != snapshot_id:
                raise ValueError("Evidence 必须属于当前快照")
            parent_id = _value(item, "parent_id")
            if parent_id and str(parent_id) in pending:
                continue
            file_id = checked_file(item)
            content = _value(item, "content", "") or ""
            connection.execute(
                """INSERT INTO evidence_units (
                       id, logical_id, snapshot_id, file_id, parent_id, unit_type, identity_key, language,
                       title, symbol_name, start_line, end_line, start_column, end_column, content, content_hash, token_count,
                       parser_name, parser_version, metadata_json
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (evidence_id, _value(item, "logical_id"), snapshot_id, file_id, parent_id,
                 _first(item, "unit_type", "evidence_type", "kind", default="text"),
                 _first(item, "identity_key", "logical_id"),
                 _first(item, "language", default=_metadata(item).get("language")), _value(item, "title"),
                 _metadata(item).get("symbol_name"), _value(item, "start_line"), _value(item, "end_line"),
                 _value(item, "start_column", 0), _value(item, "end_column", 0), content, _value(item, "content_hash") or hashlib.sha256(content.encode()).hexdigest(),
                 _first(item, "token_count", default=None),
                 _first(item, "parser_name", default=_metadata(item).get("parser", "unknown")),
                 _first(item, "parser_version", default=_metadata(item).get("parser_version", "unknown")),
                 _json(_value(item, "metadata"))),
            )
            del pending[evidence_id]
            inserted += 1
        if inserted == 0:
            raise ValueError("Evidence parent_id 存在循环或引用了不存在的父节点")

    for item in symbol_list:
        if str(_value(item, "snapshot_id")) != snapshot_id:
            raise ValueError("Symbol 必须属于当前快照")
        file_id = checked_file(item)
        connection.execute(
            """INSERT INTO symbols (
                   id, logical_id, snapshot_id, file_id, evidence_id, qualified_name, name, symbol_kind,
                   identity_key, signature, start_line, end_line, start_column, end_column, discriminator, visibility, metadata_json
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (_value(item, "id"), _value(item, "logical_id"), snapshot_id, file_id,
             _value(item, "evidence_id"), _value(item, "qualified_name"), _value(item, "name"),
             _first(item, "symbol_kind", "kind"), _first(item, "identity_key", "logical_id"),
             _value(item, "signature"), _value(item, "start_line"), _value(item, "end_line"),
             _value(item, "start_column", 0), _value(item, "end_column", 0), _value(item, "discriminator"),
             _value(item, "visibility"), _json(_value(item, "metadata"))),
        )

    valid_evidence_ids = {str(_value(item, "id")) for item in evidence_list}
    valid_symbol_ids = {str(_value(item, "id")) for item in symbol_list}

    for item in relation_list:
        if str(_value(item, "snapshot_id")) != snapshot_id:
            raise ValueError("Relation 必须属于当前快照")
        checked_file(item)
        metadata = _metadata(item)
        source_id = _first(item, "source_symbol_id", "source_id")
        source_evidence_id = _first(item, "source_evidence_id", default=metadata.get("source_evidence_id"))
        # 部分结构关系（例如配置键层级）以 Evidence 作为起点，不能把 Evidence ID 写进 Symbol 外键。
        if source_id and source_id not in valid_symbol_ids and source_id in valid_evidence_ids:
            source_evidence_id = source_evidence_id or source_id
            source_id = None
        target_id = _first(item, "target_symbol_id", "target_id")
        target_evidence_id = _first(item, "target_evidence_id", default=metadata.get("target_evidence_id"))
        if target_id and target_id not in valid_symbol_ids and target_id in valid_evidence_ids:
            target_evidence_id = target_evidence_id or target_id
            target_id = None
        connection.execute(
            """INSERT INTO relations (
                   id, snapshot_id, source_symbol_id, source_evidence_id, target_symbol_id,
                   target_evidence_id, target_ref, relation_type, identity_key, observed, inferred,
                   resolver_status, confidence, evidence_id, line, column, extractor, extractor_version, metadata_json
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (_value(item, "id"), snapshot_id, source_id,
             source_evidence_id,
             target_id,
             target_evidence_id,
             _value(item, "target_ref"), _first(item, "relation_type", "kind"),
             _first(item, "identity_key", "id"), int(bool(_value(item, "observed", False))),
             int(bool(_value(item, "inferred", False))), _value(item, "resolver_status", "unknown"),
             _value(item, "confidence"), _value(item, "evidence_id"), _value(item, "line"), _value(item, "column", 0),
             _first(item, "extractor", default=_metadata(item).get("parser", "unknown")),
             _first(item, "extractor_version", default=_metadata(item).get("parser_version", "unknown")),
             _json(_value(item, "metadata"))),
        )

    for item in diagnostic_list:
        if str(_value(item, "snapshot_id")) != snapshot_id:
            raise ValueError("Diagnostic 必须属于当前快照")
        file_id = checked_file(item)
        identity = _first(item, "identity_key", default="|".join(
            str(_value(item, key, "")) for key in
            ("file_id", "severity", "code", "message", "start_line", "end_line", "parser")
        ))
        connection.execute(
            """INSERT INTO parser_diagnostics (
                   snapshot_id, file_id, severity, code, message, start_line, end_line, parser, identity_key
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (snapshot_id, file_id, _value(item, "severity", "warning"),
             _value(item, "code", "parser_diagnostic"), _value(item, "message", ""),
             _value(item, "start_line"), _value(item, "end_line"),
             _value(item, "parser", "unknown"), identity),
        )

def replace_snapshot_parse_results(repo_id: str, snapshot_id: str, file_id: str,
                                   evidence_units: Iterable[Any], symbols: Iterable[Any],
                                   relations: Iterable[Any], diagnostics: Iterable[Any]) -> dict[str, int]:
    """在一个事务中原子覆盖单文件事实；约束冲突时恢复旧数据。"""
    evidence_list, symbol_list = list(evidence_units), list(symbols)
    relation_list, diagnostic_list = list(relations), list(diagnostics)
    with get_connection() as connection:
        _selected_snapshot(connection, repo_id, snapshot_id)
        row = connection.execute(
            "SELECT id FROM files WHERE id = ? AND repo_id = ? AND snapshot_id = ?",
            (file_id, repo_id, snapshot_id),
        ).fetchone()
        if row is None:
            raise ValueError("文件不存在或不属于指定快照")
        # 删除所有与该文件旧事实相连的边，避免保留已经失效的跨文件解析结果。
        symbol_ids = [item["id"] for item in connection.execute(
            "SELECT id FROM symbols WHERE snapshot_id = ? AND file_id = ?", (snapshot_id, file_id)
        ).fetchall()]
        evidence_ids = [item["id"] for item in connection.execute(
            "SELECT id FROM evidence_units WHERE snapshot_id = ? AND file_id = ?", (snapshot_id, file_id)
        ).fetchall()]
        if symbol_ids or evidence_ids:
            symbol_marks = ",".join("?" for _ in symbol_ids) or "NULL"
            evidence_marks = ",".join("?" for _ in evidence_ids) or "NULL"
            connection.execute(
                f"""DELETE FROM relations WHERE snapshot_id = ? AND (
                       source_symbol_id IN ({symbol_marks}) OR target_symbol_id IN ({symbol_marks}) OR
                       source_evidence_id IN ({evidence_marks}) OR target_evidence_id IN ({evidence_marks}) OR
                       evidence_id IN ({evidence_marks}))""",
                [snapshot_id, *symbol_ids, *symbol_ids, *evidence_ids, *evidence_ids, *evidence_ids],
            )
        connection.execute("DELETE FROM parser_diagnostics WHERE snapshot_id = ? AND file_id = ?", (snapshot_id, file_id))
        connection.execute("DELETE FROM symbols WHERE snapshot_id = ? AND file_id = ?", (snapshot_id, file_id))
        connection.execute("DELETE FROM evidence_units WHERE snapshot_id = ? AND file_id = ?", (snapshot_id, file_id))
        _insert_parse_facts(connection, repo_id, snapshot_id, evidence_list, symbol_list,
                            relation_list, diagnostic_list, expected_file_id=file_id)
    return {"evidence_units": len(evidence_list), "symbols": len(symbol_list),
            "relations": len(relation_list), "diagnostics": len(diagnostic_list)}


def replace_all_snapshot_parse_results(repo_id: str, snapshot_id: str, evidence_units: Iterable[Any],
                                       symbols: Iterable[Any], relations: Iterable[Any],
                                       diagnostics: Iterable[Any]) -> dict[str, int]:
    """在一个事务内原子替换整个快照的解析事实；任一冲突都会整体回滚。"""
    evidence_list, symbol_list = list(evidence_units), list(symbols)
    relation_list, diagnostic_list = list(relations), list(diagnostics)
    with get_connection() as connection:
        _selected_snapshot(connection, repo_id, snapshot_id)
        connection.execute("DELETE FROM parser_diagnostics WHERE snapshot_id = ?", (snapshot_id,))
        connection.execute("DELETE FROM relations WHERE snapshot_id = ?", (snapshot_id,))
        connection.execute("DELETE FROM symbols WHERE snapshot_id = ?", (snapshot_id,))
        connection.execute("DELETE FROM evidence_units WHERE snapshot_id = ?", (snapshot_id,))
        _insert_parse_facts(connection, repo_id, snapshot_id, evidence_list, symbol_list,
                            relation_list, diagnostic_list, expected_file_id=None)
    return {"evidence_units": len(evidence_list), "symbols": len(symbol_list),
            "relations": len(relation_list), "diagnostics": len(diagnostic_list)}


def project_evidence_to_chunks(repo_id: str, snapshot_id: str) -> int:
    """从规范 Evidence 重建旧 chunks 读模型，使旧搜索和详情 API 不变。"""
    with get_connection() as connection:
        _selected_snapshot(connection, repo_id, snapshot_id)
        connection.execute("DELETE FROM chunks WHERE repo_id = ? AND snapshot_id = ?", (repo_id, snapshot_id))
        rows = connection.execute(
            """SELECT evidence.*, files.relative_path AS file_path
               FROM evidence_units evidence JOIN files ON files.id = evidence.file_id
               WHERE evidence.snapshot_id = ? ORDER BY evidence.file_id, evidence.start_line, evidence.id""",
            (snapshot_id,),
        ).fetchall()
        for row in rows:
            connection.execute(
                """INSERT INTO chunks (
                       id, repo_id, snapshot_id, file_id, file_path, chunk_type, title, symbol_name,
                       start_line, end_line, content, content_hash, token_count, embedding_status,
                       source_type, metadata_json, parent_id
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)""",
                (row["id"], repo_id, snapshot_id, row["file_id"], row["file_path"], row["unit_type"],
                 row["title"], row["symbol_name"], row["start_line"], row["end_line"], row["content"],
                 row["content_hash"], row["token_count"], row["unit_type"], row["metadata_json"], row["parent_id"]),
            )
        # Evidence 投影是生产 ingest 的写入入口，必须在同一事务内同步更新 FTS。
        replace_snapshot_fts_rows(connection, repo_id, snapshot_id)
    return len(rows)


def list_evidence_units(repo_id: str, snapshot_id: str | None = None, file_id: str | None = None,
                        limit: int = 100, query: str | None = None) -> list[dict]:
    """按快照查询 Evidence，默认读取 active。"""
    with get_connection() as connection:
        selected = _selected_snapshot(connection, repo_id, snapshot_id)
        clauses, params = ["evidence.snapshot_id IS ?"], [selected]
        if file_id:
            clauses.append("evidence.file_id = ?")
            params.append(file_id)
        if query and query.strip():
            pattern = f"%{query.strip()}%"
            clauses.append("(evidence.content LIKE ? OR evidence.title LIKE ? OR evidence.symbol_name LIKE ?)")
            params.extend([pattern, pattern, pattern])
        params.append(max(1, min(int(limit), 1000)))
        rows = connection.execute(
            f"""SELECT evidence.*, files.relative_path AS file_path
                FROM evidence_units evidence JOIN files ON files.id = evidence.file_id
                WHERE {' AND '.join(clauses)} ORDER BY evidence.file_id, evidence.start_line, evidence.id LIMIT ?""",
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def get_evidence_unit(repo_id: str, evidence_id: str, snapshot_id: str | None = None) -> dict | None:
    """读取单条 Evidence，禁止跨仓库快照访问。"""
    with get_connection() as connection:
        selected = _selected_snapshot(connection, repo_id, snapshot_id)
        row = connection.execute(
            """SELECT evidence.*, files.relative_path AS file_path
               FROM evidence_units evidence JOIN files ON files.id = evidence.file_id
               WHERE evidence.snapshot_id IS ? AND evidence.id = ?""", (selected, evidence_id)
        ).fetchone()
    return dict(row) if row else None


def list_symbols(repo_id: str, snapshot_id: str | None = None, query: str | None = None,
                 limit: int | None = 100) -> list[dict]:
    """按名称或限定名查询 Symbol，默认读取 active。"""
    with get_connection() as connection:
        selected = _selected_snapshot(connection, repo_id, snapshot_id)
        params, where = [selected], "symbols.snapshot_id IS ?"
        if query and query.strip():
            pattern = f"%{query.strip()}%"
            where += " AND (symbols.name LIKE ? OR symbols.qualified_name LIKE ? OR symbols.signature LIKE ?)"
            params.extend([pattern, pattern, pattern])
        sql = f"""SELECT symbols.*, files.relative_path AS file_path
                   FROM symbols JOIN files ON files.id = symbols.file_id
                   WHERE {where} ORDER BY symbols.qualified_name, symbols.id"""
        if limit is not None:
            sql += " LIMIT ?"
            params.append(max(1, min(int(limit), 1000)))
        rows = connection.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def list_relations(repo_id: str, snapshot_id: str | None = None, limit: int | None = 10000) -> list[dict]:
    """查询同一快照内的规范化关系。"""
    with get_connection() as connection:
        selected = _selected_snapshot(connection, repo_id, snapshot_id)
        sql = "SELECT * FROM relations WHERE snapshot_id IS ? ORDER BY relation_type, id"
        params: list[Any] = [selected]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(max(1, min(int(limit), 10000)))
        rows = connection.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def list_parser_diagnostics(repo_id: str, snapshot_id: str | None = None,
                            file_id: str | None = None, limit: int = 1000) -> list[dict]:
    """查询解析诊断，供 API 和旧图谱诊断投影使用。"""
    with get_connection() as connection:
        selected = _selected_snapshot(connection, repo_id, snapshot_id)
        clauses, params = ["snapshot_id IS ?"], [selected]
        if file_id:
            clauses.append("file_id = ?")
            params.append(file_id)
        params.append(max(1, min(int(limit), 10000)))
        rows = connection.execute(
            f"SELECT * FROM parser_diagnostics WHERE {' AND '.join(clauses)} ORDER BY file_id, id LIMIT ?", params
        ).fetchall()
    return [dict(row) for row in rows]
