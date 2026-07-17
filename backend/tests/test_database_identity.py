"""数据库身份路径规范化回归测试。"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from service.core.database_identity import canonical_database_path, compute_database_identity


def test_database_identity_resolves_directory_symlink(tmp_path: Path) -> None:
    """同一个数据库经真实目录或目录链接访问时必须得到相同身份。"""
    real_dir = tmp_path / "real-data"
    real_dir.mkdir()
    database = real_dir / "repomind.sqlite3"
    database.touch()
    linked_dir = tmp_path / "linked-data"
    try:
        linked_dir.symlink_to(real_dir, target_is_directory=True)
    except OSError:
        # Windows 未启用开发者模式时创建链接可能被系统拒绝；正常路径断言仍覆盖健康启动。
        assert compute_database_identity(database) == compute_database_identity(database.resolve())
        return

    assert canonical_database_path(linked_dir / database.name) == canonical_database_path(database)
    assert compute_database_identity(linked_dir / database.name) == compute_database_identity(database)


def test_windows_canonical_path_is_case_insensitive(monkeypatch, tmp_path: Path) -> None:
    """Windows 分支统一大小写和分隔符，匹配 Electron 的规范。"""
    import service.core.database_identity as identity

    monkeypatch.setattr(identity.os, "name", "nt")
    monkeypatch.setattr(identity.os.path, "realpath", lambda _path: r"C:\Users\Example\RepoMind.SQLite3")
    canonical = canonical_database_path(tmp_path / "ignored.sqlite3")
    assert canonical == "c:/users/example/repomind.sqlite3"


def test_database_identity_hashes_canonical_utf8_path(tmp_path: Path) -> None:
    """身份值严格使用规范路径的 UTF-8 字节计算 SHA-256。"""
    database = tmp_path / "中文数据" / "RepoMind.SQLite3"
    database.parent.mkdir()
    database.touch()
    canonical = canonical_database_path(database)

    assert "\\" not in canonical
    assert compute_database_identity(database) == hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_smoke_backend_imports_canonical_database_identity_helper() -> None:
    """冻结后端 smoke 复用生产算法，不能维护一份易漂移的路径规范副本。"""
    script = (Path(__file__).parents[2] / "scripts" / "smoke_backend.ps1").read_text(encoding="utf-8")

    assert "from service.core.database_identity import compute_database_identity" in script
    assert "pathlib.Path(sys.argv[1]).resolve()" not in script
