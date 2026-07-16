"""
这个文件负责发现、校验并应用 SQLite 数据库迁移。
它在修改已有数据库前先做完整性检查和同目录备份，再用独立事务原子应用全部待执行迁移。
"""
from __future__ import annotations

import hashlib
import importlib
import pkgutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from service.storage import migrations as migrations_package


@dataclass(frozen=True)
class Migration:
    """一条不可变迁移的运行时描述。"""

    version: int
    name: str
    sql: str
    checksum: str
    required_columns: dict[str, dict[str, str]] | None = None
    required_indexes: dict[str, tuple[str, str]] | None = None
    data_migration: object | None = None
    data_migration_version: str | None = None
    preflight: object | None = None


@dataclass(frozen=True)
class CompatibleSignature:
    """一个允许升级的已知开发迁移签名及其结构验证器。"""

    name: str
    checksum: str
    schema_validator: Callable[[sqlite3.Connection], bool]


# 只允许经过审计的旧签名；名称、checksum 和数据库结构必须同时匹配。
# 7abb... 是未发布的 repository_snapshots 实验版，只用于升级已有测试/开发副本。
KNOWN_COMPATIBLE_SIGNATURES = {
    3: (
        CompatibleSignature(
            name="repository_snapshots",
            checksum="7abbc173351f26a9d7935cb47447cf20e1f1d938efc58d8f691a1b6d2728bb09",
            schema_validator=lambda connection: _matches_experimental_v3_schema(connection),
        ),
    ),
}


def get_latest_schema_version() -> str:
    """返回代码支持的最新迁移版本。"""
    migrations = _load_migrations()
    return str(migrations[-1].version) if migrations else "0"


def get_database_schema_version(connection: sqlite3.Connection) -> str:
    """读取当前数据库实际完成的最高迁移版本，新空库返回 0。"""
    if not _migration_table_exists(connection):
        return "0"
    row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    return str(int(row[0])) if row and row[0] is not None else "0"


def run_migrations(connection: sqlite3.Connection, database_path: Path) -> Path | None:
    """校验数据库并应用待执行迁移，返回本次创建的备份路径。"""
    database_path = Path(database_path)
    connection.execute("PRAGMA foreign_keys = ON")
    _verify_integrity(connection)
    _verify_foreign_keys(connection)

    migrations = _load_migrations()
    has_migration_table = _migration_table_exists(connection)
    applied = _load_applied_migrations(connection) if has_migration_table else {}
    _verify_applied_migrations(connection, applied, migrations)

    pending = [migration for migration in migrations if migration.version not in applied]
    if not pending:
        _verify_foreign_keys(connection)
        return None

    # 先备份、后修改；旧库的备份保持迁移前的原始状态。
    backup_path = _backup_database(connection, database_path) if _has_existing_database(database_path) else None
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("DROP TABLE IF EXISTS temp.migration_runner_initial_applied")
        connection.execute(
            "CREATE TEMP TABLE migration_runner_initial_applied (version INTEGER PRIMARY KEY)"
        )
        connection.executemany(
            "INSERT INTO temp.migration_runner_initial_applied (version) VALUES (?)",
            [(version,) for version in applied],
        )
        _ensure_migration_table(connection)
        # 获得写锁后必须重新读取，避免两个进程都按锁前的 pending 列表重复执行迁移。
        locked_applied = _load_applied_migrations(connection)
        _verify_applied_migrations(connection, locked_applied, migrations)
        pending = [migration for migration in migrations if migration.version not in locked_applied]
        for migration in pending:
            if callable(migration.preflight):
                migration.preflight(connection)
            _execute_sql_statements(connection, migration.sql)
            _ensure_required_columns(connection, migration.required_columns or {})
            _ensure_required_indexes(connection, migration.required_indexes or {})
            _run_data_migration(connection, migration)
            connection.execute(
                """
                INSERT INTO schema_migrations (version, name, checksum)
                VALUES (?, ?, ?)
                """,
                (migration.version, migration.name, migration.checksum),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise

    _verify_integrity(connection)
    _verify_foreign_keys(connection)
    return backup_path


def _load_migrations() -> list[Migration]:
    """按版本号加载 migrations 包中的迁移模块。"""
    loaded: list[Migration] = []
    prefix = f"{migrations_package.__name__}."
    for module_info in pkgutil.iter_modules(migrations_package.__path__, prefix):
        short_name = module_info.name.rsplit(".", 1)[-1]
        if not short_name.startswith("v"):
            continue
        module = importlib.import_module(module_info.name)
        version = int(module.VERSION)
        name = str(module.NAME)
        sql = str(module.SQL)
        required_columns = getattr(module, "REQUIRED_COLUMNS", None)
        required_indexes = getattr(module, "REQUIRED_INDEXES", None)
        data_migration = getattr(module, "migrate_data", None)
        preflight = getattr(module, "preflight", None)
        data_migration_version = getattr(module, "DATA_MIGRATION_CHECKSUM", None)
        if data_migration_version is None:
            data_migration_version = getattr(module, "DATA_MIGRATION_VERSION", None)
        if callable(data_migration) and not isinstance(data_migration_version, str):
            raise RuntimeError(f"数据迁移 v{version:03d} 必须定义 DATA_MIGRATION_VERSION 或 DATA_MIGRATION_CHECKSUM")
        checksum_source = (
            sql
            + repr(required_columns or {})
            + repr(required_indexes or {})
            + (data_migration_version or "")
        )
        checksum = hashlib.sha256(checksum_source.encode("utf-8")).hexdigest()
        loaded.append(
            Migration(
                version=version,
                name=name,
                sql=sql,
                checksum=checksum,
                required_columns=required_columns,
                required_indexes=required_indexes,
                data_migration=data_migration,
                data_migration_version=data_migration_version,
                preflight=preflight,
            )
        )

    loaded.sort(key=lambda migration: migration.version)
    versions = [migration.version for migration in loaded]
    if len(versions) != len(set(versions)):
        raise RuntimeError("检测到重复的数据库迁移版本")
    return loaded


def _migration_table_exists(connection: sqlite3.Connection) -> bool:
    """检查旧库是否已经启用版本化迁移。"""
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
    ).fetchone()
    return row is not None


def _ensure_migration_table(connection: sqlite3.Connection) -> None:
    """创建迁移元数据表；该表不属于业务旧表，不会覆盖已有对象。"""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            checksum TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def _load_applied_migrations(connection: sqlite3.Connection) -> dict[int, tuple[str, str]]:
    """读取数据库已经登记的迁移版本、名称和校验和。"""
    rows = connection.execute(
        "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
    ).fetchall()
    return {int(row[0]): (str(row[1]), str(row[2])) for row in rows}


def _verify_applied_migrations(
    connection: sqlite3.Connection,
    applied: dict[int, tuple[str, str]],
    migrations: list[Migration],
) -> None:
    """拒绝未知签名，只放行名称、checksum、结构均精确匹配的已知历史。"""
    available = {migration.version: migration for migration in migrations}
    for version, (stored_name, stored_checksum) in applied.items():
        migration = available.get(version)
        if migration is None:
            raise RuntimeError(f"数据库包含当前程序未知的迁移版本: {version}")
        if stored_name == migration.name and stored_checksum == migration.checksum:
            continue
        compatible = KNOWN_COMPATIBLE_SIGNATURES.get(version, ())
        if any(
            stored_name == signature.name
            and stored_checksum == signature.checksum
            and signature.schema_validator(connection)
            for signature in compatible
        ):
            continue
        raise RuntimeError(f"数据库迁移 {version} 的名称或校验和不匹配，或结构指纹不匹配")


def _table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    """读取表列名，供已知签名的结构指纹校验。"""
    return {
        str(row[1])
        for row in connection.execute(f'PRAGMA table_info("{table_name}")').fetchall()
    }


def _table_sql(connection: sqlite3.Connection, table_name: str) -> str:
    """读取并规范化建表 SQL，防止同列名的弱表伪造兼容历史。"""
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table_name,)
    ).fetchone()
    return "".join(str(row[0] or "").lower().split()) if row else ""


def _index_columns(connection: sqlite3.Connection, index_name: str) -> tuple[str, ...]:
    """读取索引列序，确保关键唯一约束并非仅有同名列。"""
    return tuple(str(row[2]) for row in connection.execute(f'PRAGMA index_info("{index_name}")'))


def _has_unique_index(connection: sqlite3.Connection, table_name: str, columns: tuple[str, ...]) -> bool:
    """验证表具备指定列序的唯一索引或 UNIQUE 约束。"""
    for row in connection.execute(f'PRAGMA index_list("{table_name}")'):
        if int(row[2]) and _index_columns(connection, str(row[1])) == columns:
            return True
    return False


def _matches_experimental_v3_schema(connection: sqlite3.Connection) -> bool:
    """只放行经审计的实验 v3 repository_snapshots 完整结构。"""
    expected_sql = "".join(
        """
        CREATE TABLE repository_snapshots (
            id TEXT PRIMARY KEY, repo_id TEXT NOT NULL,
            commit_hash TEXT NOT NULL CHECK (length(trim(commit_hash)) > 0), branch TEXT,
            status TEXT NOT NULL DEFAULT 'building'
              CHECK (status IN ('building', 'succeeded', 'failed', 'cancelled')),
            error TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, completed_at TEXT,
            FOREIGN KEY (repo_id) REFERENCES repos(id), UNIQUE(repo_id, commit_hash)
        )
        """.lower().split()
    )
    snapshot_sql = _table_sql(connection, "repository_snapshots")
    if snapshot_sql != expected_sql or _table_columns(connection, "snapshots"):
        return False
    table_info = {str(row[1]): row for row in connection.execute("PRAGMA table_info(repository_snapshots)")}
    if table_info.get("id", (None, None, None, None, 0))[5] != 1:
        return False
    if table_info.get("repo_id", (None, None, None, 0))[3] != 1:
        return False
    if table_info.get("status", (None, None, None, 0))[3] != 1:
        return False
    foreign_keys = {(str(row[3]), str(row[2]), str(row[4])) for row in connection.execute("PRAGMA foreign_key_list(repository_snapshots)")}
    if ("repo_id", "repos", "id") not in foreign_keys:
        return False
    if not _has_unique_index(connection, "repository_snapshots", ("repo_id", "commit_hash")):
        return False
    index_sql = _table_sql(connection, "repository_snapshots")
    index_row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = 'idx_repository_snapshots_repo_created'"
    ).fetchone()
    if not index_row or "".join(str(index_row[0]).lower().split()) != (
        "createindexidx_repository_snapshots_repo_createdonrepository_snapshots(repo_id,created_atdesc)"
    ):
        return False
    required = {
        "repos": "active_snapshot_id", "files": "snapshot_id", "chunks": "snapshot_id",
        "jobs": "snapshot_id", "sessions": "snapshot_id", "code_nodes": "snapshot_id",
        "code_edges": "snapshot_id", "analysis_reports": "snapshot_id",
    }
    return all(column in _table_columns(connection, table) for table, column in required.items())


def _verify_integrity(connection: sqlite3.Connection) -> None:
    """运行 SQLite 完整性检查，损坏数据库不能继续迁移。"""
    rows = connection.execute("PRAGMA integrity_check").fetchall()
    results = [str(row[0]) for row in rows]
    if results != ["ok"]:
        detail = "; ".join(results)
        raise RuntimeError(f"SQLite integrity_check 失败: {detail}")


def _verify_foreign_keys(connection: sqlite3.Connection) -> None:
    """拒绝任何外键悬挂记录，避免无待执行迁移时绕过安全检查。"""
    rows = connection.execute("PRAGMA foreign_key_check").fetchall()
    if rows:
        detail = "; ".join("/".join(str(value) for value in row) for row in rows)
        raise RuntimeError(f"SQLite foreign_key_check 失败: {detail}")


def _has_existing_database(database_path: Path) -> bool:
    """判断目标是否是需要保护的已有磁盘数据库。"""
    return str(database_path) != ":memory:" and database_path.exists() and database_path.stat().st_size > 0


def _backup_database(connection: sqlite3.Connection, database_path: Path) -> Path:
    """使用 SQLite 在线备份 API 在数据库同目录生成一致性副本。"""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = database_path.with_name(f"{database_path.name}.backup-{timestamp}")
    backup_connection = sqlite3.connect(str(backup_path))
    try:
        connection.backup(backup_connection)
    finally:
        backup_connection.close()
    return backup_path


def _ensure_required_columns(
    connection: sqlite3.Connection,
    required_columns: dict[str, dict[str, str]],
) -> None:
    """按实际表结构补列，避免旧库因 v001 的 IF NOT EXISTS 静默缺列。"""
    for table_name, columns in required_columns.items():
        table_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        if table_exists is None:
            continue
        existing = {
            str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table_name}")').fetchall()
        }
        for column_name, definition in columns.items():
            if column_name in existing:
                continue
            connection.execute(
                f'ALTER TABLE "{table_name}" ADD COLUMN "{column_name}" {definition}'
            )


def _ensure_required_indexes(
    connection: sqlite3.Connection,
    required_indexes: dict[str, tuple[str, str]],
) -> None:
    """仅在目标表和列都存在时创建索引，兼容历史不完整 schema。"""
    for index_name, (table_name, column_name) in required_indexes.items():
        existing_columns = {
            str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table_name}")').fetchall()
        }
        if column_name not in existing_columns:
            continue
        connection.execute(
            f'CREATE INDEX IF NOT EXISTS "{index_name}" ON "{table_name}"("{column_name}")'
        )


def _run_data_migration(connection: sqlite3.Connection, migration: Migration) -> None:
    """在同一迁移事务内执行可选的数据回填函数。"""
    if callable(migration.data_migration):
        migration.data_migration(connection)


def _execute_sql_statements(connection: sqlite3.Connection, sql: str) -> None:
    """逐条执行迁移 SQL，避免 executescript 隐式提交破坏外层事务。"""
    statement = ""
    for line in sql.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            if statement.strip():
                try:
                    connection.execute(statement)
                except sqlite3.OperationalError as exc:
                    # v001 可能面对同名但缺列的历史表；索引留给 v002 补列后安全创建。
                    if "no such column" not in str(exc).lower() or not statement.lstrip().upper().startswith("CREATE INDEX"):
                        raise
            statement = ""
    if statement.strip():
        raise RuntimeError("迁移 SQL 末尾存在不完整语句")
