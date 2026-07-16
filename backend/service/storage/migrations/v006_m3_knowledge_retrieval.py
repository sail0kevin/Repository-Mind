"""
这个迁移为 M3 建立统一的知识检索扩展版本。
当前先加入 FTS5/BM25 与检索审计；Embedding 和 Catalog 将继续在同一个未发布的 v006 中统一补齐。
"""
from __future__ import annotations

VERSION = 6
NAME = "m3_knowledge_retrieval"
DATA_MIGRATION_VERSION = "2026-07-16.lexical.1"

SQL = """
CREATE VIRTUAL TABLE evidence_fts USING fts5(
    evidence_id UNINDEXED,
    repo_id UNINDEXED,
    snapshot_id UNINDEXED,
    content,
    title,
    symbol,
    path,
    language,
    config_key,
    tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TABLE retrieval_runs (
    id TEXT PRIMARY KEY,
    repo_id TEXT NOT NULL,
    snapshot_id TEXT,
    query TEXT NOT NULL,
    normalized_query TEXT NOT NULL,
    retrieval_type TEXT NOT NULL DEFAULT 'lexical',
    requested_limit INTEGER NOT NULL CHECK (requested_limit >= 1),
    candidate_count INTEGER NOT NULL DEFAULT 0 CHECK (candidate_count >= 0),
    duration_ms REAL NOT NULL DEFAULT 0 CHECK (duration_ms >= 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (repo_id) REFERENCES repos(id) ON DELETE CASCADE,
    FOREIGN KEY (snapshot_id) REFERENCES repository_snapshots(id) ON DELETE CASCADE
);

CREATE INDEX idx_retrieval_runs_repo_snapshot_created
ON retrieval_runs(repo_id, snapshot_id, created_at DESC);

CREATE TABLE retrieval_candidates (
    run_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    rank INTEGER NOT NULL CHECK (rank >= 1),
    lexical_score REAL NOT NULL,
    exact_boost REAL NOT NULL DEFAULT 0,
    final_score REAL NOT NULL,
    PRIMARY KEY (run_id, evidence_id),
    UNIQUE (run_id, rank),
    FOREIGN KEY (run_id) REFERENCES retrieval_runs(id) ON DELETE CASCADE
);

CREATE INDEX idx_retrieval_candidates_run_rank
ON retrieval_candidates(run_id, rank);

CREATE TABLE evidence_embeddings (
    id TEXT PRIMARY KEY,
    repo_id TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    dimension INTEGER NOT NULL CHECK (dimension > 0),
    content_hash TEXT NOT NULL,
    vector BLOB NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (repo_id) REFERENCES repos(id) ON DELETE CASCADE,
    FOREIGN KEY (snapshot_id) REFERENCES repository_snapshots(id) ON DELETE CASCADE,
    FOREIGN KEY (snapshot_id, evidence_id) REFERENCES evidence_units(snapshot_id, id) ON DELETE CASCADE,
    UNIQUE (snapshot_id, evidence_id, provider, model)
);

CREATE INDEX idx_evidence_embeddings_snapshot
ON evidence_embeddings(repo_id, snapshot_id);
CREATE INDEX idx_evidence_embeddings_cache
ON evidence_embeddings(provider, model, content_hash, dimension);

CREATE TABLE catalog_items (
    id TEXT NOT NULL,
    repo_id TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('symbol', 'file', 'directory', 'subsystem', 'repository_overview', 'reading_guide')),
    title TEXT NOT NULL,
    path TEXT,
    parent_id TEXT,
    summary TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    generation_method TEXT NOT NULL CHECK (generation_method IN ('rule', 'llm_enhanced')),
    model TEXT,
    prompt_version TEXT NOT NULL,
    token_count INTEGER NOT NULL DEFAULT 0 CHECK (token_count >= 0),
    source_evidence_ids_json TEXT NOT NULL DEFAULT '[]',
    freshness TEXT NOT NULL,
    known_unknowns_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE (snapshot_id, id),
    FOREIGN KEY (repo_id) REFERENCES repos(id) ON DELETE CASCADE,
    FOREIGN KEY (snapshot_id) REFERENCES repository_snapshots(id) ON DELETE CASCADE,
    FOREIGN KEY (snapshot_id, parent_id) REFERENCES catalog_items(snapshot_id, id)
);

CREATE INDEX idx_catalog_items_snapshot_kind
ON catalog_items(snapshot_id, kind, path);
CREATE INDEX idx_catalog_items_parent
ON catalog_items(snapshot_id, parent_id);
"""

TARGET_OBJECTS = (
    ("table", "evidence_fts"),
    ("table", "retrieval_runs"),
    ("table", "retrieval_candidates"),
    ("table", "evidence_embeddings"),
    ("table", "catalog_items"),
)


def preflight(connection) -> None:
    """v006 尚未登记时拒绝接管同名对象，防止弱表被误认为正式检索结构。"""
    existing = [
        name
        for object_type, name in TARGET_OBJECTS
        if connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = ? AND name = ?",
            (object_type, name),
        ).fetchone()
    ]
    if existing:
        raise RuntimeError(f"v006 目标对象已存在但迁移尚未登记，拒绝接管：{', '.join(existing)}")


def migrate_data(connection) -> None:
    """把已有兼容 chunk 回填到 FTS；以后每次快照写入会在同一事务内重建对应索引。"""
    connection.execute(
        """
        INSERT INTO evidence_fts (
            evidence_id, repo_id, snapshot_id, content, title, symbol, path, language, config_key
        )
        SELECT id, repo_id, COALESCE(snapshot_id, ''), COALESCE(content, ''), COALESCE(title, ''),
               COALESCE(symbol_name, ''), COALESCE(file_path, ''), COALESCE(chunk_type, ''), ''
        FROM chunks
        """
    )
