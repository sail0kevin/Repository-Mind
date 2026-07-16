"""验证空库和旧 schema 都能安全升级到 M0 基线。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from service.config import settings as settings_module
from service.config.settings import Paths, Settings
from service.storage.migrations import runner
from service.storage.migrations import v004_parser_evidence_storage as v004
from service.storage.migrations.runner import run_migrations
from service.storage.sqlite_db import get_connection


EXPECTED_BUSINESS_TABLES = {
    "analysis_reports",
    "chunks",
    "code_edges",
    "code_graph_diagnostics",
    "code_nodes",
    "files",
    "jobs",
    "repos",
    "sessions",
    "settings",
    "vectors",
}


def _table_names(connection: sqlite3.Connection) -> set[str]:
    """读取数据库中的用户表名，测试中忽略 SQLite 内部表。"""
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {str(row[0]) for row in rows}


def test_empty_database_applies_baseline_and_enables_foreign_keys(tmp_path: Path) -> None:
    """空库首次连接后应完整建表、登记版本且开启外键。"""
    database_path = tmp_path / "empty.sqlite3"
    connection = sqlite3.connect(database_path)
    try:
        backup_path = run_migrations(connection, database_path)

        assert backup_path is None
        assert EXPECTED_BUSINESS_TABLES <= _table_names(connection)
        assert "schema_migrations" in _table_names(connection)
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1

        migration = connection.execute(
            "SELECT version, name, length(checksum) FROM schema_migrations"
        ).fetchone()
        assert migration == (1, "baseline", 64)
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        connection.close()


def test_legacy_schema_is_preserved_backed_up_and_adopted(tmp_path: Path) -> None:
    """无迁移表的旧库应保留旧表和数据，并在同目录留下迁移前备份。"""
    database_path = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(database_path)
    connection.executescript(
        """
        CREATE TABLE repos (
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
        CREATE TABLE legacy_notes (
            id INTEGER PRIMARY KEY,
            note TEXT NOT NULL
        );
        INSERT INTO repos (id, alias, repo_path, status)
        VALUES ('repo_legacy', '旧仓库', 'G:/legacy', 'registered');
        INSERT INTO legacy_notes (note) VALUES ('必须保留');
        """
    )
    connection.commit()

    try:
        backup_path = run_migrations(connection, database_path)

        assert backup_path is not None
        assert backup_path.parent == database_path.parent
        assert backup_path.exists()
        assert "legacy_notes" in _table_names(connection)
        assert connection.execute("SELECT note FROM legacy_notes").fetchone()[0] == "必须保留"
        assert connection.execute("SELECT alias FROM repos").fetchone()[0] == "旧仓库"
        assert EXPECTED_BUSINESS_TABLES <= _table_names(connection)
        assert connection.execute("SELECT version FROM schema_migrations").fetchone()[0] == 1

        # 备份必须是迁移前快照：含旧数据，但不应提前出现迁移元数据表。
        backup_connection = sqlite3.connect(backup_path)
        try:
            assert "legacy_notes" in _table_names(backup_connection)
            assert "schema_migrations" not in _table_names(backup_connection)
            assert backup_connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            backup_connection.close()
    finally:
        connection.close()


def test_get_connection_initializes_database_through_runner(tmp_path: Path, monkeypatch) -> None:
    """业务连接入口必须通过 runner 初始化 schema，而不是继续调用旧建表逻辑。"""
    database_path = tmp_path / "entrypoint.sqlite3"
    test_settings = Settings(paths=Paths(data_dir=tmp_path, database_path=database_path))
    monkeypatch.setattr(settings_module, "_settings", test_settings)

    with get_connection() as connection:
        assert "schema_migrations" in _table_names(connection)
        assert "repos" in _table_names(connection)
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_applied_migration_checksum_mismatch_is_rejected(tmp_path: Path) -> None:
    """迁移文件与数据库登记的校验和不一致时必须停止启动。"""
    database_path = tmp_path / "checksum.sqlite3"
    connection = sqlite3.connect(database_path)
    try:
        run_migrations(connection, database_path)
        connection.execute("UPDATE schema_migrations SET checksum = 'tampered' WHERE version = 1")
        connection.commit()

        try:
            run_migrations(connection, database_path)
        except RuntimeError as error:
            assert "校验和不匹配" in str(error)
        else:
            raise AssertionError("被篡改的迁移校验和未被拒绝")
    finally:
        connection.close()



def test_authoritative_history_v003_upgrades_to_v004(tmp_path: Path) -> None:
    """真实 CLI v3 的权威 name/checksum/schema 必须直接升级到 schema 4。"""
    database_path = tmp_path / "historical-v3.sqlite3"
    connection = sqlite3.connect(database_path)
    try:
        run_migrations(connection, database_path)
        connection.execute("DELETE FROM schema_migrations WHERE version = 4")
        connection.execute("DROP TABLE evidence_embeddings")
        for table in ("parser_diagnostics", "relations", "symbols", "evidence_units", "repository_snapshots"):
            connection.execute(f'DROP TABLE "{table}"')
        connection.commit()
        run_migrations(connection, database_path)
        assert connection.execute("SELECT name, checksum FROM schema_migrations WHERE version = 3").fetchone() == (
            "snapshot_data_model", "ab0d054d997a3f5ef659295a363d17fa0fa2d785bbdce7c4be9ec206fd740689")
        assert "repository_snapshots" in _table_names(connection)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()


def test_known_experimental_v003_requires_exact_structure(tmp_path: Path) -> None:
    """7abb 开发签名只在 repository_snapshots 结构指纹存在时放行。"""
    database_path = tmp_path / "experimental-v3.sqlite3"
    connection = sqlite3.connect(database_path)
    try:
        run_migrations(connection, database_path)
        connection.execute("DELETE FROM schema_migrations WHERE version IN (3, 4, 6, 7)")
        connection.execute("DROP TABLE agent_trace_steps")
        connection.execute("DROP TABLE agent_traces")
        connection.execute("DROP TABLE evidence_embeddings")
        connection.execute("DROP TABLE catalog_items")
        connection.execute("DROP TABLE retrieval_candidates")
        connection.execute("DROP TABLE retrieval_runs")
        connection.execute("DROP TABLE evidence_fts")
        for name in ("trg_repository_snapshots_mirror_insert", "trg_repository_snapshots_mirror_update"):
            connection.execute(f'DROP TRIGGER "{name}"')
        connection.execute("DROP TABLE snapshots")
        for table in ("parser_diagnostics", "relations", "symbols", "evidence_units"):
            connection.execute(f'DROP TABLE "{table}"')
        connection.execute("INSERT INTO schema_migrations (version, name, checksum) VALUES (3, ?, ?)",
                           ("repository_snapshots", "7abbc173351f26a9d7935cb47447cf20e1f1d938efc58d8f691a1b6d2728bb09"))
        connection.commit()
        run_migrations(connection, database_path)
        assert connection.execute("SELECT name FROM schema_migrations WHERE version = 4").fetchone()
        connection.execute("INSERT INTO repos (id, alias, repo_path, status) VALUES ('repo_1', '实验仓库', 'Z:/fixture', 'registered')")
        connection.execute(
            "INSERT INTO repository_snapshots (id, repo_id, commit_hash, status) VALUES ('experimental_snapshot', 'repo_1', 'abc', 'succeeded')"
        )
        assert connection.execute("SELECT commit_sha FROM snapshots WHERE id = 'experimental_snapshot'").fetchone() == ("abc",)
    finally:
        connection.close()


def test_experimental_v003_weak_same_name_table_is_rejected(tmp_path: Path) -> None:
    """同名弱表即使列名相同，也不能伪造实验白名单。"""
    database_path = tmp_path / "experimental-v3-weak.sqlite3"
    connection = sqlite3.connect(database_path)
    try:
        run_migrations(connection, database_path)
        connection.execute("DELETE FROM schema_migrations WHERE version IN (3, 4, 6, 7)")
        connection.execute("DROP TABLE agent_trace_steps")
        connection.execute("DROP TABLE agent_traces")
        connection.execute("DROP TABLE evidence_embeddings")
        connection.execute("DROP TABLE catalog_items")
        connection.execute("DROP TABLE retrieval_candidates")
        connection.execute("DROP TABLE retrieval_runs")
        connection.execute("DROP TABLE evidence_fts")
        for name in ("trg_repository_snapshots_mirror_insert", "trg_repository_snapshots_mirror_update"):
            connection.execute(f'DROP TRIGGER "{name}"')
        connection.execute("DROP TABLE snapshots")
        for table in ("parser_diagnostics", "relations", "symbols", "evidence_units"):
            connection.execute(f'DROP TABLE "{table}"')
        connection.execute("DROP TABLE repository_snapshots")
        connection.execute("CREATE TABLE repository_snapshots (id TEXT, repo_id TEXT, commit_hash TEXT, branch TEXT, status TEXT, error TEXT, created_at TEXT, updated_at TEXT, started_at TEXT, completed_at TEXT)")
        connection.execute("INSERT INTO schema_migrations (version, name, checksum) VALUES (3, ?, ?)", ("repository_snapshots", "7abbc173351f26a9d7935cb47447cf20e1f1d938efc58d8f691a1b6d2728bb09"))
        connection.commit()
        try:
            run_migrations(connection, database_path)
        except RuntimeError as error:
            assert "结构指纹不匹配" in str(error)
        else:
            raise AssertionError("伪造的弱 repository_snapshots 表未被拒绝")
    finally:
        connection.close()


def test_no_pending_foreign_key_violation_is_rejected(tmp_path: Path) -> None:
    """无待执行迁移也必须检查外键悬挂记录，且不会产生新备份。"""
    database_path = tmp_path / "foreign-key-violation.sqlite3"
    connection = sqlite3.connect(database_path)
    try:
        run_migrations(connection, database_path)
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("INSERT INTO files (id, repo_id, relative_path, absolute_path) VALUES ('orphan', 'missing', 'x', 'x')")
        connection.commit()
        try:
            run_migrations(connection, database_path)
        except RuntimeError as error:
            assert "foreign_key_check" in str(error)
        else:
            raise AssertionError("无 pending 时的外键违规未被拒绝")
        assert not list(tmp_path.glob("foreign-key-violation.sqlite3.backup-*"))
    finally:
        connection.close()


def test_data_migration_version_changes_checksum(monkeypatch) -> None:
    """数据迁移的显式版本必须进入 checksum，源码格式不参与。"""
    before = next(migration for migration in runner._load_migrations() if migration.version == 4).checksum
    monkeypatch.setattr(v004, "DATA_MIGRATION_VERSION", "test-version-bump")
    after = next(migration for migration in runner._load_migrations() if migration.version == 4).checksum
    assert after != before
    assert next(migration for migration in runner._load_migrations() if migration.version == 3).checksum == ("ab0d054d997a3f5ef659295a363d17fa0fa2d785bbdce7c4be9ec206fd740689")
def test_electron_legacy_schema_import_is_idempotent_and_preserves_source(tmp_path: Path) -> None:
    """Electron 旧表应幂等导入、保留来源表并跳过敏感设置。"""
    database_path = tmp_path / "electron-copy.sqlite3"
    connection = sqlite3.connect(database_path)
    connection.executescript("""
        CREATE TABLE repos (id TEXT PRIMARY KEY, alias TEXT NOT NULL, repo_path TEXT NOT NULL,
            remote_url TEXT, branch TEXT, commit_hash TEXT, indexed_commit_hash TEXT,
            status TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE file_records (id TEXT PRIMARY KEY, repo_id TEXT NOT NULL, relative_path TEXT NOT NULL,
            absolute_path TEXT NOT NULL, language TEXT, file_type TEXT NOT NULL, extension TEXT,
            size_bytes INTEGER NOT NULL, line_count INTEGER, is_binary INTEGER NOT NULL DEFAULT 0,
            is_test_file INTEGER NOT NULL DEFAULT 0, ignored_reason TEXT, hash TEXT, mtime REAL,
            parse_status TEXT NOT NULL, summary TEXT);
        CREATE TABLE chunk_records (id TEXT PRIMARY KEY, repo_id TEXT NOT NULL, file_id TEXT NOT NULL,
            chunk_type TEXT NOT NULL, title TEXT, symbol_name TEXT, start_line INTEGER, end_line INTEGER,
            content TEXT NOT NULL, content_hash TEXT NOT NULL, token_count INTEGER,
            embedding_status TEXT NOT NULL, source_type TEXT NOT NULL, metadata_json TEXT, parent_id TEXT);
        CREATE TABLE chunk_embeddings (chunk_id TEXT PRIMARY KEY, repo_id TEXT NOT NULL,
            embedding_model TEXT NOT NULL, vector_json TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);
        INSERT INTO repos VALUES ('legacy_repo', '旧库', 'Z:/missing', NULL, 'main', NULL, NULL, 'indexed', '2025-01-01');
        INSERT INTO file_records VALUES ('file_1', 'legacy_repo', 'a.py', 'Z:/missing/a.py', 'python', 'text', '.py', 10, 1, 0, 0, NULL, 'h', 1.5, 'parsed', '摘要');
        INSERT INTO chunk_records VALUES ('chunk_1', 'legacy_repo', 'file_1', 'function', NULL, 'f', 1, 1, 'def f(): pass', 'ch', 4, 'embedded', 'code', '{}', NULL);
        INSERT INTO chunk_embeddings VALUES ('chunk_1', 'legacy_repo', 'repomind-hash-embedding-v1', '[0.0, 1.0]', '2025-01-02');
        INSERT INTO app_settings VALUES ('theme', '"dark"', '2025-01-03');
        INSERT INTO app_settings VALUES ('llm_api_key', '"secret"', '2025-01-03');
    """)
    connection.commit()
    try:
        run_migrations(connection, database_path)
        first = tuple(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                      for table in ("repos", "files", "chunks", "vectors", "repository_snapshots"))
        run_migrations(connection, database_path)
        second = tuple(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                       for table in ("repos", "files", "chunks", "vectors", "repository_snapshots"))
        assert first == second == (1, 1, 1, 1, 1)
        assert "file_records" in _table_names(connection)
        assert connection.execute("SELECT snapshot_id FROM files WHERE id = 'file_1'").fetchone()[0] == "legacy_legacy_repo"
        assert connection.execute("SELECT value FROM settings WHERE key = 'theme'").fetchone()[0] == '"dark"'
        assert connection.execute("SELECT 1 FROM settings WHERE key = 'llm_api_key'").fetchone() is None
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()


def test_v004_rejects_preexisting_weak_target_table_and_rolls_back(tmp_path: Path) -> None:
    """未登记 v004 时出现同名残缺表必须拒绝，且不能登记迁移成功。"""
    database_path = tmp_path / "weak-v004.sqlite3"
    connection = sqlite3.connect(database_path)
    try:
        run_migrations(connection, database_path)
        for table in ("parser_diagnostics", "relations", "symbols", "evidence_units"):
            connection.execute(f'DROP TABLE "{table}"')
        connection.execute("DELETE FROM schema_migrations WHERE version = 4")
        connection.execute("DROP TABLE evidence_embeddings")
        connection.execute("CREATE TABLE evidence_units (id TEXT)")
        connection.commit()

        try:
            run_migrations(connection, database_path)
        except RuntimeError as error:
            assert "拒绝接管" in str(error)
        else:
            raise AssertionError("预存弱表未被 v004 拒绝")

        assert connection.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = 4"
        ).fetchone()[0] == 0
        assert [row[1] for row in connection.execute(
            "PRAGMA table_info(evidence_units)"
        )] == ["id"]
        assert "symbols" not in _table_names(connection)
    finally:
        connection.close()
