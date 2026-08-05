"""用新代码重建 context-holdout 索引，然后跑 audit 对比。

新代码包含：chunk_splitter（P0）、结构化 Embedding 输入（P2）、
Python 超长函数语法边界拆分（P1）、Markdown overlap（P0）。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
for p in (str(PROJECT_ROOT), str(BACKEND_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from service.config import settings as settings_module
from service.config.settings import Paths, Settings
from service.core.ingest_service import ingest_repository_snapshot
from service.storage.models import RepoCreateRequest
from service.storage.sqlite_db import reset_database_initialization, get_connection

MANIFEST_PATH = PROJECT_ROOT / ".tmp-context-holdout" / "context-holdout.local.manifest.json"
DATA_DIR = PROJECT_ROOT / ".tmp-context-holdout" / "repomind-data"


def main() -> int:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8-sig"))
    repo_path = Path(manifest["repository"]["path"])
    old_repo_id = manifest["index"]["repo_id"]

    print(f"=== 重建索引 ===")
    print(f"仓库: {repo_path}")
    print(f"数据目录: {DATA_DIR}")

    # 指向同一个数据库
    settings_module._settings = Settings(paths=Paths(data_dir=DATA_DIR, database_path=DATA_DIR / "repomind.sqlite3"))
    reset_database_initialization()

    # 直接删除旧数据库，让 ingest 重新建表（避免外键清理顺序问题）
    db_path = DATA_DIR / "repomind.sqlite3"
    if db_path.exists():
        db_path.unlink()
        print(f"已删除旧数据库: {db_path}")
    # 重置初始化状态，让下次连接重新建表
    reset_database_initialization()

    # 重新注册并 ingest
    from service.api.v1.repos import create_repository
    print(f"\n注册仓库并 ingest...")
    registration = create_repository(RepoCreateRequest(
        repo_path=str(repo_path),
        alias="context-holdout-rebuild",
        remote_url=None,
        branch=None,
    ))
    print(f"新 repo_id: {registration.repo_id}")

    result = ingest_repository_snapshot(registration.repo_id)
    print(f"\n=== Ingest 完成 ===")
    print(f"snapshot_id: {result.snapshot_id}")
    print(f"status: {result.status}")
    print(f"indexed_files: {result.indexed_file_count}")
    print(f"chunk_count: {result.chunk_count}")
    print(f"embedding_status: {result.embedding_status}")

    # 统计新索引的 evidence 数量（应该比旧的 3790 多，因为 chunk_splitter 拆分了超长 evidence）
    with get_connection() as conn:
        ev_count = conn.execute("SELECT COUNT(*) FROM evidence_units WHERE snapshot_id = ?",
                                (result.snapshot_id,)).fetchone()[0]
        ch_count = conn.execute("SELECT COUNT(*) FROM chunks WHERE snapshot_id = ?",
                                (result.snapshot_id,)).fetchone()[0]
    print(f"\n新 evidence_units: {ev_count} (旧: 3790)")
    print(f"新 chunks: {ch_count} (旧: 3790)")

    # 更新 manifest 指向新索引
    manifest["index"]["repo_id"] = registration.repo_id
    manifest["index"]["snapshot_id"] = result.snapshot_id
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8-sig")
    print(f"\nmanifest 已更新: repo_id={registration.repo_id}, snapshot_id={result.snapshot_id}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
