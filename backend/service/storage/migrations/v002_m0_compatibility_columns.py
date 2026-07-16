"""
这个迁移补齐历史数据库可能缺少的 M0 列。
它不改写 v001；runner 会先检查实际表结构，只对缺失列执行 ALTER TABLE。
"""

VERSION = 2
NAME = "m0_compatibility_columns"
SQL = ""

# SQLite 不支持通用的 ADD COLUMN IF NOT EXISTS，因此由 runner 逐列安全检查。
REQUIRED_COLUMNS = {
    "files": {
        "absolute_path": "TEXT",
        "language": "TEXT",
        "file_type": "TEXT",
        "extension": "TEXT",
        "size_bytes": "INTEGER",
        "line_count": "INTEGER",
        "is_binary": "INTEGER NOT NULL DEFAULT 0",
        "is_test_file": "INTEGER NOT NULL DEFAULT 0",
        "ignored_reason": "TEXT",
        "hash": "TEXT",
        "parse_status": "TEXT",
    },
    "jobs": {
        "repo_id": "TEXT",
        "progress": "REAL NOT NULL DEFAULT 0",
        "message": "TEXT",
        "error": "TEXT",
        "started_at": "TEXT",
        "finished_at": "TEXT",
        "created_at": "TEXT",
        "updated_at": "TEXT",
    },
    "code_nodes": {
        "name": "TEXT",
        "node_type": "TEXT",
        "file_path": "TEXT",
        "start_line": "INTEGER",
        "end_line": "INTEGER",
        "signature": "TEXT",
    },
    "code_edges": {
        "source_id": "TEXT",
        "target_id": "TEXT",
        "edge_type": "TEXT",
    },
}

# 补列完成后重新确保这些索引存在；v001 遇到历史缺列时会暂时跳过对应索引。
REQUIRED_INDEXES = {
    "idx_files_repo": ("files", "repo_id"),
    "idx_chunks_repo": ("chunks", "repo_id"),
    "idx_jobs_repo": ("jobs", "repo_id"),
}
