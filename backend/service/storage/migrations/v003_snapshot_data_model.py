"""
这个迁移引入仓库快照（Snapshot）数据模型。
它只新增表、可空列和索引，历史记录保持 snapshot_id 为 NULL，因此旧数据和旧 API 都能继续使用。
"""

VERSION = 3
NAME = "snapshot_data_model"

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
"""

# SQLite 没有通用的 ADD COLUMN IF NOT EXISTS，交给 runner 按实际表结构安全补列。
REQUIRED_COLUMNS = {
    "repos": {
        "active_snapshot_id": "TEXT REFERENCES snapshots(id)",
    },
    "files": {
        "snapshot_id": "TEXT REFERENCES snapshots(id)",
    },
    "chunks": {
        "snapshot_id": "TEXT REFERENCES snapshots(id)",
    },
    "jobs": {
        "snapshot_id": "TEXT REFERENCES snapshots(id)",
    },
    "sessions": {
        "snapshot_id": "TEXT REFERENCES snapshots(id)",
    },
    "code_nodes": {
        "snapshot_id": "TEXT REFERENCES snapshots(id)",
    },
    "code_edges": {
        "snapshot_id": "TEXT REFERENCES snapshots(id)",
    },
    "analysis_reports": {
        "snapshot_id": "TEXT REFERENCES snapshots(id)",
    },
}

# 单列索引兼容现有查询，并为后续按快照隔离数据提供基础。
REQUIRED_INDEXES = {
    "idx_repos_active_snapshot": ("repos", "active_snapshot_id"),
    "idx_files_snapshot": ("files", "snapshot_id"),
    "idx_chunks_snapshot": ("chunks", "snapshot_id"),
    "idx_jobs_snapshot": ("jobs", "snapshot_id"),
    "idx_sessions_snapshot": ("sessions", "snapshot_id"),
    "idx_code_nodes_snapshot": ("code_nodes", "snapshot_id"),
    "idx_code_edges_snapshot": ("code_edges", "snapshot_id"),
    "idx_analysis_reports_snapshot": ("analysis_reports", "snapshot_id"),
}
