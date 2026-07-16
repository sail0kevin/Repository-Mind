"""M4 Main Agent 执行轨迹迁移。"""

VERSION = 7
NAME = "m4_agent_traces"

SQL = """
CREATE TABLE agent_traces (
    id TEXT PRIMARY KEY,
    repo_id TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    session_id TEXT,
    entrypoint TEXT NOT NULL,
    question TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'auto',
    status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed', 'fallback')),
    planner_version TEXT NOT NULL,
    final_answer TEXT,
    confidence TEXT,
    token_count INTEGER NOT NULL DEFAULT 0 CHECK (token_count >= 0),
    error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    FOREIGN KEY (repo_id) REFERENCES repos(id) ON DELETE CASCADE,
    FOREIGN KEY (snapshot_id) REFERENCES repository_snapshots(id) ON DELETE CASCADE,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE SET NULL
);

CREATE INDEX idx_agent_traces_repo_snapshot_created
ON agent_traces(repo_id, snapshot_id, created_at DESC);

CREATE TABLE agent_trace_steps (
    id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    step_no INTEGER NOT NULL,
    step_type TEXT NOT NULL,
    tool_name TEXT,
    status TEXT NOT NULL CHECK (status IN ('started', 'succeeded', 'failed', 'skipped')),
    input_json TEXT NOT NULL DEFAULT '{}',
    output_summary_json TEXT NOT NULL DEFAULT '{}',
    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
    token_count INTEGER NOT NULL DEFAULT 0 CHECK (token_count >= 0),
    duration_ms REAL,
    error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    FOREIGN KEY (trace_id) REFERENCES agent_traces(id) ON DELETE CASCADE,
    UNIQUE (trace_id, step_no)
);

CREATE INDEX idx_agent_trace_steps_trace_order
ON agent_trace_steps(trace_id, step_no);
"""
