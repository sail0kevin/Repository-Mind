"""M3 SQLite FTS5 词法索引、查询归一化和检索运行追踪。"""
from __future__ import annotations

import re
import sqlite3
import time
import uuid
from typing import Any

from service.storage.sqlite_db import get_connection

# 中文连续文本、拉丁字母和数字分别取词；camelCase 会在下一步补充分段。
_TOKEN_RE = re.compile(r"[㐀-鿿]+|[A-Za-z]+|\d+")
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def normalize_query(query: str) -> list[str]:
    """把中文、snake_case、camelCase 和路径查询展开为稳定去重词项。"""
    normalized = query.replace("\\", "/").strip()
    terms: list[str] = []
    for raw in _TOKEN_RE.findall(normalized):
        if re.fullmatch(r"[㐀-鿿]+", raw):
            # FTS5 unicode61 不做中文分词，保留完整短语，同时补单字提高召回。
            terms.append(raw)
            if len(raw) > 1:
                terms.extend(raw)
            continue
        camel_parts = [part for part in _CAMEL_BOUNDARY_RE.split(raw) if part]
        terms.append(raw.lower())
        if len(camel_parts) > 1:
            terms.extend(part.lower() for part in camel_parts)
    # 保持首次出现顺序，避免相同词项改变 MATCH 表达式和运行记录。
    return list(dict.fromkeys(term for term in terms if term))


def normalized_query_text(query: str) -> str:
    """返回供运行追踪和索引辅助列使用的空格分隔归一化文本。"""
    return " ".join(normalize_query(query))


def _fts_match_expression(terms: list[str]) -> str:
    """使用双引号构造纯词项 OR 查询，禁止用户输入进入 FTS5 语法。"""
    escaped = [term.replace('"', '""') for term in terms]
    return " OR ".join(f'"{term}"' for term in escaped)


def replace_snapshot_fts_rows(connection, repo_id: str, snapshot_id: str | None) -> int:
    """在当前事务中从 chunks 重建一个快照的 FTS 行。"""
    stored_snapshot = snapshot_id or ""
    connection.execute(
        "DELETE FROM evidence_fts WHERE repo_id = ? AND snapshot_id = ?",
        (repo_id, stored_snapshot),
    )
    rows = connection.execute(
        """SELECT id, content, title, symbol_name, file_path, chunk_type, metadata_json
           FROM chunks WHERE repo_id = ? AND snapshot_id IS ?""",
        (repo_id, snapshot_id),
    ).fetchall()
    for row in rows:
        content = row["content"] or ""
        title = row["title"] or ""
        symbol = row["symbol_name"] or ""
        path = row["file_path"] or ""
        language = row["chunk_type"] or ""
        # 辅助列收录字段归一化结果，使 camel/snake/path 和配置键可被同一 MATCH 查询召回。
        config_key = normalized_query_text(" ".join((title, symbol, path, language, content)))
        connection.execute(
            """INSERT INTO evidence_fts (
                   evidence_id, repo_id, snapshot_id, content, title, symbol, path, language, config_key
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (row["id"], repo_id, stored_snapshot, content, title, symbol, path, language, config_key),
        )
    return len(rows)


def rebuild_snapshot_fts(repo_id: str, snapshot_id: str | None) -> int:
    """为兼容写入路径公开一个可独立调用的索引重建入口。"""
    with get_connection() as connection:
        return replace_snapshot_fts_rows(connection, repo_id, snapshot_id)


def _exact_boost(row: Any, query: str, terms: list[str]) -> float:
    """对标识符和路径精确命中加权，避免正文词频淹没用户明确目标。"""
    raw = query.strip().replace("\\", "/").casefold()
    symbol = (row["symbol_name"] or "").casefold()
    title = (row["title"] or "").casefold()
    path = (row["file_path"] or "").replace("\\", "/").casefold()
    boost = 0.0
    if raw and raw == symbol:
        boost += 12.0
    elif raw and raw == title:
        boost += 8.0
    if raw and raw == path:
        boost += 14.0
    elif raw and (path.endswith("/" + raw) or path.rsplit("/", 1)[-1] == raw):
        boost += 10.0
    normalized_targets = {normalized_query_text(symbol), normalized_query_text(title)}
    if terms and " ".join(terms) in normalized_targets:
        boost += 4.0
    return boost


def search_fts_chunks(
    repo_id: str,
    query: str,
    limit: int = 10,
    snapshot_id: str | None = None,
) -> list[dict]:
    """用 FTS5 bm25 在单一快照内检索，并记录候选排名。"""
    terms = normalize_query(query)
    if not terms:
        return []
    safe_limit = max(1, min(int(limit), 50))
    candidate_limit = min(max(safe_limit * 5, 25), 250)
    started = time.perf_counter()
    run_id = f"retrieval_{uuid.uuid4().hex}"
    match_expression = _fts_match_expression(terms)
    with get_connection() as connection:
        selected = snapshot_id
        if selected is None:
            active = connection.execute(
                "SELECT active_snapshot_id FROM repos WHERE id = ?", (repo_id,)
            ).fetchone()
            selected = active["active_snapshot_id"] if active else None
        stored_snapshot = selected or ""
        try:
            rows = connection.execute(
                """SELECT chunks.*,
                          bm25(evidence_fts, 1.0, 3.0, 5.0, 4.0, 1.5, 2.0) AS bm25_rank
                   FROM evidence_fts
                   JOIN chunks ON chunks.id = evidence_fts.evidence_id
                   WHERE evidence_fts MATCH ?
                     AND evidence_fts.repo_id = ?
                     AND evidence_fts.snapshot_id = ?
                     AND chunks.repo_id = ?
                     AND chunks.snapshot_id IS ?
                   ORDER BY bm25_rank ASC
                   LIMIT ?""",
                (match_expression, repo_id, stored_snapshot, repo_id, selected, candidate_limit),
            ).fetchall()
        except sqlite3.OperationalError as exc:
            # unicode61 对连续中文短语可能无法按单字 OR 查询，回退到完整短语仍保持 FTS5/BM25。
            if not any(any("㐀" <= char <= "鿿" for char in term) for term in terms):
                raise
            phrase = query.strip().replace('"', '""')
            try:
                rows = connection.execute(
                    """SELECT chunks.*,
                              bm25(evidence_fts, 1.0, 3.0, 5.0, 4.0, 1.5, 2.0) AS bm25_rank
                       FROM evidence_fts
                       JOIN chunks ON chunks.id = evidence_fts.evidence_id
                       WHERE evidence_fts MATCH ?
                         AND evidence_fts.repo_id = ?
                         AND evidence_fts.snapshot_id = ?
                         AND chunks.repo_id = ?
                         AND chunks.snapshot_id IS ?
                       ORDER BY bm25_rank ASC
                       LIMIT ?""",
                    (f'"{phrase}"', repo_id, stored_snapshot, repo_id, selected, candidate_limit),
                ).fetchall()
            except sqlite3.OperationalError:
                raise exc
        scored: list[tuple[float, float, Any]] = []
        for row in rows:
            # SQLite bm25 越小越好（常见值为负数），转换成越大越好的稳定正分数。
            lexical_score = max(0.0, -float(row["bm25_rank"] or 0.0))
            boost = _exact_boost(row, query, terms)
            scored.append((lexical_score + boost, boost, row))
        scored.sort(key=lambda item: (-item[0], item[2]["file_path"] or "", item[2]["id"]))
        elapsed_ms = (time.perf_counter() - started) * 1000
        connection.execute(
            """INSERT INTO retrieval_runs (
                   id, repo_id, snapshot_id, query, normalized_query, retrieval_type,
                   requested_limit, candidate_count, duration_ms
               ) VALUES (?, ?, ?, ?, ?, 'lexical', ?, ?, ?)""",
            (run_id, repo_id, selected, query, " ".join(terms), safe_limit, len(scored), elapsed_ms),
        )
        results: list[dict] = []
        for rank, (score, boost, row) in enumerate(scored[:safe_limit], start=1):
            data = dict(row)
            data.pop("bm25_rank", None)
            data["vector_score"] = 0.0
            data["score"] = float(score)
            data["match_type"] = "lexical"
            data["retrieval_run_id"] = run_id
            results.append(data)
            connection.execute(
                """INSERT INTO retrieval_candidates (
                       run_id, evidence_id, rank, lexical_score, exact_boost, final_score
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                (run_id, row["id"], rank, score - boost, boost, score),
            )
    return results
