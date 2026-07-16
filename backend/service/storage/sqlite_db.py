"""
这个文件负责 SQLite 数据库连接与进程内一次性初始化。
迁移和完整性检查只在每个数据库路径首次连接时执行，普通业务连接只设置必要 PRAGMA。
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from service.config.settings import get_settings
from service.storage.migrations import run_migrations

_INITIALIZE_LOCK = threading.Lock()
_INITIALIZED_DATABASES: set[str] = set()


def require_fts5(connection: sqlite3.Connection) -> None:
    """启动时实际创建临时 FTS5 表，缺少能力时给出明确错误。"""
    try:
        connection.execute("CREATE VIRTUAL TABLE temp.__repomind_fts5_check USING fts5(content)")
        connection.execute("DROP TABLE temp.__repomind_fts5_check")
    except sqlite3.OperationalError as exc:
        raise RuntimeError("当前 SQLite 未启用 FTS5，无法启动 RepoMind 词法检索") from exc


def reset_database_initialization(database_path: Path | str | None = None) -> None:
    """测试切换临时数据库时清理进程内初始化缓存。"""
    with _INITIALIZE_LOCK:
        if database_path is None:
            _INITIALIZED_DATABASES.clear()
        else:
            _INITIALIZED_DATABASES.discard(str(database_path))


def _configure_connection(connection: sqlite3.Connection, database_path: Path) -> None:
    """为每条连接设置并发和约束参数。"""
    connection.execute("PRAGMA busy_timeout = 30000")
    connection.execute("PRAGMA foreign_keys = ON")
    if str(database_path) != ":memory:":
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")


def _ensure_initialized(connection: sqlite3.Connection, database_path: Path) -> None:
    """在进程内串行且只执行一次迁移，避免每个请求都跑 integrity_check。"""
    key = str(database_path)
    if key in _INITIALIZED_DATABASES:
        return
    with _INITIALIZE_LOCK:
        if key in _INITIALIZED_DATABASES:
            return
        require_fts5(connection)
        run_migrations(connection, database_path)
        _INITIALIZED_DATABASES.add(key)


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    """提供一个带自动提交/回滚事务的 SQLite 连接。"""
    settings = get_settings()
    database_path = settings.paths.database_path
    connection = sqlite3.connect(str(database_path), timeout=30.0)
    connection.row_factory = sqlite3.Row
    try:
        _configure_connection(connection, database_path)
        _ensure_initialized(connection, database_path)
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
