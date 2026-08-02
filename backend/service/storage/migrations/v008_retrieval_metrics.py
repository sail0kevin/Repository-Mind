"""P2-2 在线检索质量指标。"""

VERSION = 8
NAME = "retrieval_metrics"

SQL = """
CREATE TABLE retrieval_metrics (
    id TEXT PRIMARY KEY,
    repo_id TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    retrieval_mode TEXT NOT NULL,
    query TEXT NOT NULL,
    returned_count INTEGER NOT NULL DEFAULT 0 CHECK (returned_count >= 0),
    top_score REAL,
    duration_ms REAL NOT NULL CHECK (duration_ms >= 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (repo_id) REFERENCES repos(id) ON DELETE CASCADE,
    FOREIGN KEY (snapshot_id) REFERENCES repository_snapshots(id) ON DELETE CASCADE
);

CREATE INDEX idx_retrieval_metrics_repo_created
ON retrieval_metrics(repo_id, created_at DESC);

CREATE INDEX idx_retrieval_metrics_snapshot_created
ON retrieval_metrics(snapshot_id, created_at DESC);
"""
