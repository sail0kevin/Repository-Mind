"""后端测试共享 fixture：每条测试使用独立数据库，并提供一个最小混合仓库。"""
from __future__ import annotations

from pathlib import Path

import pytest

from service.config import settings as settings_module
from service.config.settings import Paths, Settings
from service.storage.sqlite_db import reset_database_initialization


@pytest.fixture(autouse=True)
def temporary_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把全局数据库单例替换到临时目录，防止测试读写用户的真实 RepoMind 数据。"""
    data_dir = tmp_path / "data"
    database_path = data_dir / "repomind.sqlite3"
    # 这里直接创建父目录，因为测试注入的是 Settings 实例，不会再经过 get_settings 的首次初始化分支。
    data_dir.mkdir(parents=True, exist_ok=True)
    test_settings = Settings(paths=Paths(data_dir=data_dir, database_path=database_path))
    monkeypatch.setattr(settings_module, "_settings", test_settings)
    reset_database_initialization()
    yield database_path
    # 测试结束后清空单例和初始化缓存，后续测试不会沿用已经删除的临时路径。
    reset_database_initialization()
    monkeypatch.setattr(settings_module, "_settings", None)


@pytest.fixture
def mixed_repository(tmp_path: Path) -> Path:
    """建立同时含源码、测试、文档、二进制、未知类型和忽略目录的最小仓库。"""
    repo = tmp_path / "mixed-repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "src").mkdir()
    (repo / "tests").mkdir()
    (repo / "assets").mkdir()
    (repo / "node_modules").mkdir()

    (repo / "src" / "app.py").write_text("print('一')\nprint('二')\n", encoding="utf-8")
    (repo / "tests" / "test_app.py").write_text("def test_app():\n    assert True\n", encoding="utf-8")
    (repo / "widget.spec.ts").write_text("test('widget', () => true)\n", encoding="utf-8")
    (repo / "README.md").write_text("# 示例仓库\n\n用于扫描测试。", encoding="utf-8")
    (repo / "empty.txt").write_bytes(b"")
    (repo / "utf16.txt").write_text("第一行\n第二行", encoding="utf-16")
    (repo / "assets" / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00binary")
    (repo / "notes.custom").write_text("未知扩展名不应进入索引", encoding="utf-8")
    (repo / "node_modules" / "ignored.js").write_text("ignored", encoding="utf-8")
    return repo
