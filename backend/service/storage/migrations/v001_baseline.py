"""
这个文件定义 M0 的基线数据库结构。
基线只使用 IF NOT EXISTS 创建缺失对象，因此可以接管旧库而不会删除旧表或旧数据。
"""

VERSION = 1
NAME = "baseline"

# SQL 文本本身参与校验和计算；迁移发布后不要直接修改，应新增更高版本迁移。
SQL = """
CREATE TABLE IF NOT EXISTS repos (
    id TEXT PRIMARY KEY,
    alias TEXT NOT NULL,
    repo_path TEXT NOT NULL,
    remote_url TEXT,
    branch TEXT,
    commit_hash TEXT,
    status TEXT NOT NULL,
    file_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS files (
    id TEXT PRIMARY KEY,
    repo_id TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    absolute_path TEXT,
    language TEXT,
    file_type TEXT,
    extension TEXT,
    size_bytes INTEGER,
    line_count INTEGER,
    is_binary INTEGER NOT NULL DEFAULT 0,
    is_test_file INTEGER NOT NULL DEFAULT 0,
    ignored_reason TEXT,
    hash TEXT,
    parse_status TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (repo_id) REFERENCES repos(id)
);

CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY,
    repo_id TEXT NOT NULL,
    file_id TEXT,
    file_path TEXT,
    chunk_type TEXT,
    title TEXT,
    symbol_name TEXT,
    start_line INTEGER,
    end_line INTEGER,
    content TEXT,
    content_hash TEXT,
    token_count INTEGER,
    embedding_status TEXT,
    source_type TEXT,
    metadata_json TEXT,
    parent_id TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (repo_id) REFERENCES repos(id)
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    repo_id TEXT,
    job_type TEXT NOT NULL,
    status TEXT NOT NULL,
    progress REAL NOT NULL DEFAULT 0,
    message TEXT,
    error TEXT,
    started_at TEXT,
    finished_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    repo_id TEXT,
    question TEXT,
    answer TEXT,
    trace_id TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (repo_id) REFERENCES repos(id)
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS code_nodes (
    id TEXT PRIMARY KEY,
    repo_id TEXT NOT NULL,
    name TEXT,
    node_type TEXT,
    file_path TEXT,
    start_line INTEGER,
    end_line INTEGER,
    signature TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (repo_id) REFERENCES repos(id)
);

CREATE TABLE IF NOT EXISTS code_edges (
    id TEXT PRIMARY KEY,
    repo_id TEXT NOT NULL,
    source_id TEXT,
    target_id TEXT,
    edge_type TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (repo_id) REFERENCES repos(id)
);

CREATE TABLE IF NOT EXISTS code_graph_diagnostics (
    repo_id TEXT PRIMARY KEY,
    diagnostics_json TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS vectors (
    id TEXT PRIMARY KEY,
    repo_id TEXT NOT NULL,
    chunk_id TEXT,
    embedding TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (repo_id) REFERENCES repos(id)
);

CREATE TABLE IF NOT EXISTS analysis_reports (
    id TEXT PRIMARY KEY,
    repo_id TEXT NOT NULL,
    analysis_type TEXT,
    status TEXT,
    summary TEXT,
    report_json TEXT,
    markdown TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (repo_id) REFERENCES repos(id)
);

CREATE INDEX IF NOT EXISTS idx_files_repo ON files(repo_id);
CREATE INDEX IF NOT EXISTS idx_chunks_repo ON chunks(repo_id);
CREATE INDEX IF NOT EXISTS idx_jobs_repo ON jobs(repo_id);
"""
