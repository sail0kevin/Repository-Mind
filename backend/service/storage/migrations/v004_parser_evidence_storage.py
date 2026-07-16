"""
这个迁移为 M2 增加统一解析事实表。
Evidence 是新快照的事实源，Symbol、Relation 和 Diagnostic 都必须归属于同一快照。
"""

VERSION = 4
NAME = "parser_evidence_storage"
# 数据回填实现的显式不可变版本，避免将 Python 源码格式纳入校验和。
DATA_MIGRATION_VERSION = "2026-07-16.1"

SQL = """
CREATE TABLE IF NOT EXISTS snapshots (
    id TEXT PRIMARY KEY,
    repo_id TEXT NOT NULL,
    commit_sha TEXT NOT NULL,
    branch TEXT,
    status TEXT NOT NULL DEFAULT 'building'
        CHECK (status IN ('building', 'succeeded', 'failed', 'cancelled')),
    error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    FOREIGN KEY (repo_id) REFERENCES repos(id),
    UNIQUE (repo_id, commit_sha)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_repo_created
ON snapshots(repo_id, created_at DESC);

CREATE TABLE IF NOT EXISTS repository_snapshots (
    id TEXT PRIMARY KEY,
    repo_id TEXT NOT NULL,
    commit_hash TEXT NOT NULL CHECK (length(trim(commit_hash)) > 0),
    branch TEXT,
    status TEXT NOT NULL DEFAULT 'building'
        CHECK (status IN ('building', 'succeeded', 'failed', 'cancelled')),
    error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    FOREIGN KEY (repo_id) REFERENCES repos(id),
    UNIQUE(repo_id, commit_hash)
);

CREATE INDEX IF NOT EXISTS idx_repository_snapshots_repo_created
ON repository_snapshots(repo_id, created_at DESC);

CREATE TRIGGER IF NOT EXISTS trg_repository_snapshots_mirror_insert
AFTER INSERT ON repository_snapshots
BEGIN
    INSERT OR IGNORE INTO snapshots (
        id, repo_id, commit_sha, branch, status, error,
        created_at, updated_at, finished_at
    ) VALUES (
        NEW.id, NEW.repo_id, NEW.commit_hash, NEW.branch, NEW.status, NEW.error,
        NEW.created_at, NEW.updated_at, NEW.completed_at
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_repository_snapshots_mirror_update
AFTER UPDATE ON repository_snapshots
BEGIN
    UPDATE snapshots SET
        commit_sha = NEW.commit_hash,
        branch = NEW.branch,
        status = NEW.status,
        error = NEW.error,
        updated_at = NEW.updated_at,
        finished_at = NEW.completed_at
    WHERE id = NEW.id;
END;

CREATE TABLE IF NOT EXISTS legacy_import_runs (
    source_kind TEXT PRIMARY KEY,
    source_schema TEXT NOT NULL,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status TEXT NOT NULL,
    metadata_json TEXT
);

CREATE TABLE IF NOT EXISTS legacy_record_metadata (
    source_table TEXT NOT NULL,
    source_id TEXT NOT NULL,
    target_table TEXT,
    target_id TEXT,
    metadata_json TEXT NOT NULL,
    PRIMARY KEY (source_table, source_id)
);

CREATE TABLE IF NOT EXISTS legacy_import_diagnostics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_table TEXT NOT NULL,
    source_id TEXT,
    code TEXT NOT NULL,
    message TEXT NOT NULL,
    metadata_json TEXT,
    UNIQUE(source_table, source_id, code)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_files_snapshot_identity
ON files(snapshot_id, id);

CREATE TABLE evidence_units (
    id TEXT NOT NULL,
    logical_id TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    file_id TEXT NOT NULL,
    parent_id TEXT,
    unit_type TEXT NOT NULL,
    identity_key TEXT NOT NULL,
    language TEXT,
    title TEXT,
    symbol_name TEXT,
    start_line INTEGER,
    end_line INTEGER,
    start_column INTEGER,
    end_column INTEGER,
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    token_count INTEGER,
    parser_name TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    metadata_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE (snapshot_id, id),
    FOREIGN KEY (snapshot_id) REFERENCES repository_snapshots(id) ON DELETE CASCADE,
    FOREIGN KEY (snapshot_id, file_id) REFERENCES files(snapshot_id, id) ON DELETE CASCADE,
    FOREIGN KEY (snapshot_id, parent_id) REFERENCES evidence_units(snapshot_id, id),
    CHECK (start_line IS NULL OR start_line >= 1),
    CHECK (end_line IS NULL OR end_line >= 1),
    CHECK (start_line IS NULL OR end_line IS NULL OR end_line >= start_line),
    UNIQUE (snapshot_id, identity_key)
);

CREATE INDEX IF NOT EXISTS idx_evidence_units_snapshot_file
ON evidence_units(snapshot_id, file_id, start_line);
CREATE INDEX IF NOT EXISTS idx_evidence_units_snapshot_type
ON evidence_units(snapshot_id, unit_type);
CREATE UNIQUE INDEX IF NOT EXISTS uq_evidence_units_snapshot_identity
ON evidence_units(snapshot_id, identity_key);

CREATE TABLE symbols (
    id TEXT NOT NULL,
    logical_id TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    file_id TEXT NOT NULL,
    evidence_id TEXT,
    qualified_name TEXT NOT NULL,
    name TEXT NOT NULL,
    symbol_kind TEXT NOT NULL,
    identity_key TEXT NOT NULL,
    signature TEXT,
    start_line INTEGER,
    end_line INTEGER,
    start_column INTEGER,
    end_column INTEGER,
    discriminator TEXT,
    visibility TEXT,
    metadata_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE (snapshot_id, id),
    FOREIGN KEY (snapshot_id) REFERENCES repository_snapshots(id) ON DELETE CASCADE,
    FOREIGN KEY (snapshot_id, file_id) REFERENCES files(snapshot_id, id) ON DELETE CASCADE,
    FOREIGN KEY (snapshot_id, evidence_id) REFERENCES evidence_units(snapshot_id, id),
    CHECK (start_line IS NULL OR start_line >= 1),
    CHECK (end_line IS NULL OR end_line >= 1),
    CHECK (start_line IS NULL OR end_line IS NULL OR end_line >= start_line),
    UNIQUE (snapshot_id, identity_key)
);

CREATE INDEX IF NOT EXISTS idx_symbols_snapshot_file
ON symbols(snapshot_id, file_id, start_line);
CREATE INDEX IF NOT EXISTS idx_symbols_snapshot_name
ON symbols(snapshot_id, name);
CREATE INDEX IF NOT EXISTS idx_symbols_snapshot_kind
ON symbols(snapshot_id, symbol_kind);

CREATE TABLE relations (
    id TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    source_symbol_id TEXT,
    source_evidence_id TEXT,
    target_symbol_id TEXT,
    target_evidence_id TEXT,
    target_ref TEXT,
    relation_type TEXT NOT NULL,
    identity_key TEXT NOT NULL,
    observed INTEGER NOT NULL DEFAULT 0 CHECK (observed IN (0, 1)),
    inferred INTEGER NOT NULL DEFAULT 0 CHECK (inferred IN (0, 1)),
    resolver_status TEXT NOT NULL DEFAULT 'unknown'
        CHECK (resolver_status IN ('resolved', 'unresolved', 'ambiguous', 'unknown')),
    confidence REAL,
    evidence_id TEXT,
    line INTEGER,
    column INTEGER,
    extractor TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    metadata_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE (snapshot_id, id),
    FOREIGN KEY (snapshot_id) REFERENCES repository_snapshots(id) ON DELETE CASCADE,
    FOREIGN KEY (snapshot_id, source_symbol_id) REFERENCES symbols(snapshot_id, id),
    FOREIGN KEY (snapshot_id, source_evidence_id) REFERENCES evidence_units(snapshot_id, id),
    FOREIGN KEY (snapshot_id, target_symbol_id) REFERENCES symbols(snapshot_id, id),
    FOREIGN KEY (snapshot_id, target_evidence_id) REFERENCES evidence_units(snapshot_id, id),
    FOREIGN KEY (snapshot_id, evidence_id) REFERENCES evidence_units(snapshot_id, id),
    CHECK (source_symbol_id IS NOT NULL OR source_evidence_id IS NOT NULL),
    CHECK (target_symbol_id IS NOT NULL OR target_evidence_id IS NOT NULL OR length(trim(COALESCE(target_ref, ''))) > 0),
    CHECK (confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0))
);

CREATE INDEX IF NOT EXISTS idx_relations_snapshot_source_symbol
ON relations(snapshot_id, source_symbol_id);
CREATE INDEX IF NOT EXISTS idx_relations_snapshot_target_symbol
ON relations(snapshot_id, target_symbol_id);
CREATE INDEX IF NOT EXISTS idx_relations_snapshot_type
ON relations(snapshot_id, relation_type);
CREATE UNIQUE INDEX IF NOT EXISTS uq_relations_snapshot_identity
ON relations(snapshot_id, identity_key);

CREATE TABLE parser_diagnostics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id TEXT NOT NULL,
    file_id TEXT NOT NULL,
    severity TEXT NOT NULL,
    code TEXT NOT NULL,
    message TEXT NOT NULL,
    start_line INTEGER,
    end_line INTEGER,
    parser TEXT NOT NULL,
    identity_key TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (snapshot_id) REFERENCES repository_snapshots(id) ON DELETE CASCADE,
    FOREIGN KEY (snapshot_id, file_id) REFERENCES files(snapshot_id, id) ON DELETE CASCADE,
    CHECK (start_line IS NULL OR start_line >= 1),
    CHECK (end_line IS NULL OR end_line >= 1),
    CHECK (start_line IS NULL OR end_line IS NULL OR end_line >= start_line),
    UNIQUE (snapshot_id, identity_key)
);

CREATE INDEX IF NOT EXISTS idx_parser_diagnostics_snapshot_file
ON parser_diagnostics(snapshot_id, file_id, severity);
"""

import json


REQUIRED_COLUMNS = {
    "repos": {"active_snapshot_id": "TEXT", "file_count": "INTEGER NOT NULL DEFAULT 0"},
    "files": {"snapshot_id": "TEXT"},
    "chunks": {"snapshot_id": "TEXT"},
    "jobs": {"snapshot_id": "TEXT"},
    "sessions": {"snapshot_id": "TEXT"},
    "code_nodes": {"snapshot_id": "TEXT"},
    "code_edges": {"snapshot_id": "TEXT"},
    "code_graph_diagnostics": {"snapshot_id": "TEXT"},
    "vectors": {"snapshot_id": "TEXT"},
    "analysis_reports": {"snapshot_id": "TEXT"},
}

REQUIRED_INDEXES = {
    "idx_repos_active_snapshot": ("repos", "active_snapshot_id"),
    "idx_files_snapshot": ("files", "snapshot_id"),
    "idx_chunks_snapshot": ("chunks", "snapshot_id"),
    "idx_jobs_snapshot": ("jobs", "snapshot_id"),
    "idx_sessions_snapshot": ("sessions", "snapshot_id"),
    "idx_code_nodes_snapshot": ("code_nodes", "snapshot_id"),
    "idx_code_edges_snapshot": ("code_edges", "snapshot_id"),
    "idx_code_graph_diagnostics_snapshot": ("code_graph_diagnostics", "snapshot_id"),
    "idx_vectors_snapshot": ("vectors", "snapshot_id"),
    "idx_analysis_reports_snapshot": ("analysis_reports", "snapshot_id"),
}


def _table_exists(connection, table_name: str) -> bool:
    """判断数据库中是否存在目标表。"""
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table_name,)
    ).fetchone() is not None


def _columns(connection, table_name: str) -> set[str]:
    """读取表列名，避免对实验版或历史版结构作错误假设。"""
    return {str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table_name}")')}


def _normalize_diagnostics_table(connection) -> None:
    """仅在旧诊断表无附属对象且结构精确匹配时才安全重建。"""
    if not _table_exists(connection, "code_graph_diagnostics"):
        return
    primary_key = [
        str(row[1]) for row in connection.execute("PRAGMA table_info(code_graph_diagnostics)") if row[5]
    ]
    expected_columns = {"repo_id", "diagnostics_json", "updated_at", "snapshot_id"}
    columns = _columns(connection, "code_graph_diagnostics")
    dependent_objects = connection.execute(
        "SELECT type, name FROM sqlite_master WHERE tbl_name = ? AND type IN ('index', 'trigger') AND sql IS NOT NULL AND name != 'idx_code_graph_diagnostics_snapshot'",
        ("code_graph_diagnostics",),
    ).fetchall()
    foreign_key_dependents = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND sql LIKE ? AND name != 'code_graph_diagnostics'",
        ("%code_graph_diagnostics%",),
    ).fetchall()
    if primary_key != ["repo_id"] or columns != expected_columns or dependent_objects or foreign_key_dependents:
        return
    connection.execute(
        """
        CREATE TABLE code_graph_diagnostics_m2 (
            repo_id TEXT NOT NULL,
            snapshot_id TEXT,
            diagnostics_json TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(repo_id, snapshot_id)
        )
        """
    )
    connection.execute(
        """
        INSERT INTO code_graph_diagnostics_m2
            (repo_id, snapshot_id, diagnostics_json, updated_at)
        SELECT repo_id, snapshot_id, diagnostics_json, updated_at
        FROM code_graph_diagnostics
        """
    )
    connection.execute("DROP TABLE code_graph_diagnostics")
    connection.execute("ALTER TABLE code_graph_diagnostics_m2 RENAME TO code_graph_diagnostics")


def _copy_historical_snapshots(connection) -> None:
    """把权威历史 snapshots 表无损投影到 M2 repository_snapshots。"""
    if not _table_exists(connection, "snapshots"):
        return
    connection.execute(
        """
        INSERT OR IGNORE INTO repository_snapshots (
            id, repo_id, commit_hash, branch, status, error,
            created_at, updated_at, started_at, completed_at
        )
        SELECT id, repo_id, commit_sha, branch, status, error,
               created_at, updated_at, created_at, finished_at
        FROM snapshots
        """
    )


def _bind_existing_snapshot_ids(connection) -> None:
    """保留历史 v3 已有绑定，并仅为实验 v3 的既有索引产物补 legacy 快照。"""
    bind_tables = ("files", "chunks", "vectors", "code_nodes", "code_edges", "code_graph_diagnostics")
    for repo_id, commit_hash, branch, active_snapshot_id in connection.execute(
        "SELECT id, commit_hash, branch, active_snapshot_id FROM repos"
    ).fetchall():
        if active_snapshot_id:
            exists = connection.execute(
                "SELECT 1 FROM repository_snapshots WHERE id = ? AND repo_id = ?",
                (active_snapshot_id, repo_id),
            ).fetchone()
            if exists:
                continue
        # 只有 runner 启动前已登记权威 v3 的数据库保留 NULL；无迁移表旧库仍需建立 legacy snapshot。
        historical_v3 = connection.execute(
            "SELECT 1 FROM temp.migration_runner_initial_applied WHERE version = 3"
        ).fetchone() is not None
        if historical_v3 and _table_exists(connection, "snapshots"):
            continue
        has_data = any(
            _table_exists(connection, table)
            and "repo_id" in _columns(connection, table)
            and connection.execute(f'SELECT 1 FROM "{table}" WHERE repo_id = ? LIMIT 1', (repo_id,)).fetchone()
            for table in bind_tables
        )
        if not has_data:
            continue
        normalized_commit = (commit_hash or "legacy-unknown-commit").strip() or "legacy-unknown-commit"
        preferred_id = f"legacy_{repo_id}"
        connection.execute(
            """
            INSERT OR IGNORE INTO repository_snapshots
                (id, repo_id, commit_hash, branch, status, completed_at)
            VALUES (?, ?, ?, ?, 'succeeded', CURRENT_TIMESTAMP)
            """,
            (preferred_id, repo_id, normalized_commit, branch),
        )
        snapshot_id = connection.execute(
            "SELECT id FROM repository_snapshots WHERE repo_id = ? AND commit_hash = ?",
            (repo_id, normalized_commit),
        ).fetchone()[0]
        for table in bind_tables:
            if _table_exists(connection, table) and "snapshot_id" in _columns(connection, table):
                connection.execute(
                    f'UPDATE "{table}" SET snapshot_id = ? WHERE repo_id = ? AND snapshot_id IS NULL',
                    (snapshot_id, repo_id),
                )
        connection.execute(
            "UPDATE repos SET active_snapshot_id = ? WHERE id = ? AND active_snapshot_id IS NULL",
            (snapshot_id, repo_id),
        )


def _detect_electron_legacy_schema(connection) -> bool:
    """只在 Electron 旧表组合明确存在时启动导入，避免误判普通自定义表。"""
    required = {"repos", "file_records", "chunk_records", "chunk_embeddings"}
    return all(_table_exists(connection, table) for table in required)


def _column_names(connection, table_name: str) -> list[str]:
    """按原始顺序读取列，便于完整保留无法直接映射的字段。"""
    return [str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table_name}")')]


def _row_dicts(connection, table_name: str):
    """把 legacy 行转成字典，NULL 与空字符串保持原样。"""
    columns = _column_names(connection, table_name)
    for row in connection.execute(f'SELECT * FROM "{table_name}"'):
        yield dict(zip(columns, row))


def _store_legacy_metadata(connection, source_table: str, source_id: str, target_table: str | None,
                           target_id: str | None, metadata: dict) -> None:
    """幂等保存未映射字段与来源信息，不把伪造值塞入业务列。"""
    connection.execute(
        """
        INSERT OR REPLACE INTO legacy_record_metadata
            (source_table, source_id, target_table, target_id, metadata_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (source_table, source_id, target_table, target_id,
         json.dumps(metadata, ensure_ascii=False, sort_keys=True)),
    )


def _diagnose(connection, source_table: str, source_id: str | None, code: str,
              message: str, metadata: dict | None = None) -> None:
    """记录不能可靠映射的 legacy 情况，而不是静默丢弃或猜测。"""
    connection.execute(
        """
        INSERT OR IGNORE INTO legacy_import_diagnostics
            (source_table, source_id, code, message, metadata_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (source_table, source_id, code, message,
         json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True)),
    )


def _legacy_snapshot_for_repo(connection, repo: dict) -> str:
    """为旧索引产物创建明确 legacy snapshot；未知 commit 使用诚实占位符并留诊断。"""
    repo_id = str(repo["id"])
    commit_hash = repo.get("indexed_commit_hash") or repo.get("commit_hash")
    if not commit_hash or not str(commit_hash).strip():
        commit_hash = "legacy-unknown-commit"
        _diagnose(connection, "repos", repo_id, "unknown_commit",
                  "旧仓库没有可验证的 indexed_commit_hash 或 commit_hash")
    commit_hash = str(commit_hash).strip()
    snapshot_id = f"legacy_{repo_id}"
    connection.execute(
        """
        INSERT OR IGNORE INTO repository_snapshots
            (id, repo_id, commit_hash, branch, status, completed_at)
        VALUES (?, ?, ?, ?, 'succeeded', CURRENT_TIMESTAMP)
        """,
        (snapshot_id, repo_id, commit_hash, repo.get("branch")),
    )
    actual = connection.execute(
        "SELECT id FROM repository_snapshots WHERE repo_id = ? AND commit_hash = ?",
        (repo_id, commit_hash),
    ).fetchone()
    return str(actual[0])


def _import_electron_legacy(connection) -> None:
    """事务、幂等地复制 Electron 旧表；旧表始终保留，敏感设置不写普通 settings。"""
    if not _detect_electron_legacy_schema(connection):
        return
    snapshots: dict[str, str] = {}
    for repo in _row_dicts(connection, "repos"):
        repo_id = str(repo["id"])
        connection.execute(
            """
            INSERT OR IGNORE INTO repos
                (id, alias, repo_path, remote_url, branch, commit_hash, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (repo_id, repo.get("alias") or repo_id, repo.get("repo_path") or "",
             repo.get("remote_url"), repo.get("branch"), repo.get("commit_hash"),
             repo.get("status") or "registered", repo.get("created_at")),
        )
        metadata = {key: repo.get(key) for key in (
            "last_commit_hash", "indexed_commit_hash", "default_branch", "updated_at", "last_ingested_at"
        ) if key in repo}
        _store_legacy_metadata(connection, "repos", repo_id, "repos", repo_id, metadata)
        snapshots[repo_id] = _legacy_snapshot_for_repo(connection, repo)

    for row in _row_dicts(connection, "file_records"):
        source_id, repo_id = str(row["id"]), str(row["repo_id"])
        snapshot_id = snapshots.get(repo_id)
        if snapshot_id is None:
            _diagnose(connection, "file_records", source_id, "missing_repo", "文件缺少可验证的仓库归属", row)
            continue
        connection.execute(
            """
            INSERT OR IGNORE INTO files
                (id, repo_id, relative_path, absolute_path, language, file_type, extension,
                 size_bytes, line_count, is_binary, is_test_file, ignored_reason, hash,
                 parse_status, snapshot_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (source_id, repo_id, row.get("relative_path"), row.get("absolute_path"),
             row.get("language"), row.get("file_type"), row.get("extension"), row.get("size_bytes"),
             row.get("line_count"), row.get("is_binary", 0), row.get("is_test_file", 0),
             row.get("ignored_reason"), row.get("hash"), row.get("parse_status"), snapshot_id),
        )
        _store_legacy_metadata(connection, "file_records", source_id, "files", source_id,
                               {key: row.get(key) for key in ("mtime", "summary") if key in row})

    for row in _row_dicts(connection, "chunk_records"):
        source_id, repo_id, file_id = str(row["id"]), str(row["repo_id"]), str(row["file_id"])
        snapshot_id = snapshots.get(repo_id)
        file_row = connection.execute(
            "SELECT relative_path FROM files WHERE id = ? AND repo_id = ?", (file_id, repo_id)
        ).fetchone()
        if snapshot_id is None or file_row is None:
            _diagnose(connection, "chunk_records", source_id, "missing_parent",
                      "切片缺少可验证的仓库或文件归属", row)
            continue
        connection.execute(
            """
            INSERT OR IGNORE INTO chunks
                (id, repo_id, file_id, file_path, chunk_type, title, symbol_name, start_line,
                 end_line, content, content_hash, token_count, embedding_status, source_type,
                 metadata_json, parent_id, snapshot_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (source_id, repo_id, file_id, file_row[0], row.get("chunk_type"), row.get("title"),
             row.get("symbol_name"), row.get("start_line"), row.get("end_line"), row.get("content"),
             row.get("content_hash"), row.get("token_count"), row.get("embedding_status"),
             row.get("source_type"), row.get("metadata_json"), row.get("parent_id"), snapshot_id),
        )

    for row in _row_dicts(connection, "chunk_embeddings"):
        chunk_id, repo_id = str(row["chunk_id"]), str(row["repo_id"])
        if connection.execute("SELECT 1 FROM chunks WHERE id = ? AND repo_id = ?", (chunk_id, repo_id)).fetchone() is None:
            _diagnose(connection, "chunk_embeddings", chunk_id, "missing_chunk",
                      "向量缺少可验证的 chunk 归属", {"repo_id": repo_id})
            continue
        existing_vector = connection.execute(
            "SELECT repo_id, chunk_id, embedding FROM vectors WHERE id = ?", (chunk_id,)
        ).fetchone()
        if existing_vector is not None:
            if tuple(existing_vector) != (repo_id, chunk_id, row.get("vector_json")):
                _diagnose(connection, "chunk_embeddings", chunk_id, "target_id_conflict",
                          "目标 vectors 已有同 ID 的不同记录，来源向量仅保留在 legacy metadata",
                          {"repo_id": repo_id, "embedding_model": row.get("embedding_model")})
            _store_legacy_metadata(connection, "chunk_embeddings", chunk_id, "vectors", chunk_id,
                                   {"embedding_model": row.get("embedding_model"),
                                    "vector_json": row.get("vector_json"),
                                    "created_at": row.get("created_at")})
            continue
        connection.execute(
            """
            INSERT INTO vectors (id, repo_id, chunk_id, embedding, updated_at, snapshot_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (chunk_id, repo_id, chunk_id, row.get("vector_json"), row.get("created_at"), snapshots[repo_id]),
        )
        _store_legacy_metadata(connection, "chunk_embeddings", chunk_id, "vectors", chunk_id,
                               {"embedding_model": row.get("embedding_model")})

    simple_tables = {
        "job_records": ("jobs", ("id", "repo_id", "job_type", "status", "progress", "message", "error",
                                  "started_at", "finished_at", "created_at", "updated_at")),
        "session_records": ("sessions", ("id", "repo_id", "question", "answer", "trace_id", "created_at")),
        "analysis_reports": ("analysis_reports", ("id", "repo_id", "analysis_type", "status", "summary",
                                                   "report_json", "markdown", "created_at")),
    }
    for source, (target, columns) in simple_tables.items():
        if not _table_exists(connection, source) or source == target:
            continue
        placeholders = ", ".join("?" for _ in columns)
        quoted = ", ".join(f'"{column}"' for column in columns)
        for row in _row_dicts(connection, source):
            connection.execute(
                f'INSERT OR IGNORE INTO "{target}" ({quoted}) VALUES ({placeholders})',
                tuple(row.get(column) for column in columns),
            )

    if _table_exists(connection, "app_settings"):
        for row in _row_dicts(connection, "app_settings"):
            key = str(row["key"])
            if "api_key" in key.lower() or "token" in key.lower() or "secret" in key.lower():
                _diagnose(connection, "app_settings", key, "sensitive_setting_skipped",
                          "敏感设置未写入普通 settings，必须重新配置到 secret store")
                continue
            connection.execute(
                "INSERT OR IGNORE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                (key, row.get("value"), row.get("updated_at")),
            )

    for repo_id, snapshot_id in snapshots.items():
        connection.execute(
            "UPDATE repos SET active_snapshot_id = ?, file_count = (SELECT count(*) FROM files WHERE repo_id = ?) "
            "WHERE id = ?",
            (snapshot_id, repo_id, repo_id),
        )
    connection.execute(
        """
        INSERT OR REPLACE INTO legacy_import_runs
            (source_kind, source_schema, status, metadata_json)
        VALUES ('electron', 'file_records/chunk_records/chunk_embeddings', 'succeeded', ?)
        """,
        (json.dumps({"preserved_source_tables": True}, sort_keys=True),),
    )


def migrate_data(connection) -> None:
    """在同一事务内完成历史 v3、实验 v3、Electron 旧库与 M2 结构升级。"""
    _normalize_diagnostics_table(connection)
    _copy_historical_snapshots(connection)
    _bind_existing_snapshot_ids(connection)
    _import_electron_legacy(connection)


TARGET_TABLES = ("evidence_units", "symbols", "relations", "parser_diagnostics")

def preflight(connection):
    """v004 未登记时拒绝任何预存同名业务表，避免弱结构被误当成正式表。"""
    existing = [
        name
        for name in TARGET_TABLES
        if connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (name,),
        ).fetchone()
    ]
    if existing:
        raise RuntimeError(f"v004 目标表已存在但迁移尚未登记，拒绝接管：{', '.join(existing)}")
