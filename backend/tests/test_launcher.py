from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from service import launcher
from service.mcp_server import __main__ as mcp_entry
from service.mcp_server import tools as mcp_tools
from service.storage.repository_store import list_repo_records


def _git(repo: Path, *args: str) -> None:
    """为 --index 测试建立最小 Git 仓库。"""
    subprocess.run(["git", "-C", str(repo), *args], check=True, stdout=subprocess.DEVNULL)


def test_index_flag_dispatches_to_index_runtime(monkeypatch) -> None:
    """--index 必须走 _run_index 而不是启动 HTTP 服务。"""
    called: list[bool] = []

    def fake_run_index() -> int:
        called.append(True)
        return 0

    monkeypatch.setattr(launcher, "_run_index", fake_run_index)
    monkeypatch.setattr(sys, "argv", ["repomind-backend.exe", "--index", "--repo", "/tmp/demo"])

    with pytest.raises(SystemExit) as exc:
        launcher.main()
    assert exc.value.code == 0
    assert called == [True]


def test_index_mode_builds_registered_and_indexed_repo(tmp_path: Path, monkeypatch) -> None:
    """--index 同步建索引：产出可被 MCP 发现的已索引仓库。"""
    repo = tmp_path / "cli-repo"
    repo.mkdir()
    _git(repo, "init")
    (repo / "app.py").write_text("def hello():\n    return 'hi'\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "-c", "user.name=T", "-c", "user.email=t@t", "commit", "-m", "initial")

    monkeypatch.setattr(
        sys, "argv", ["repomind-backend.exe", "--index", "--repo", str(repo), "--alias", "cli-demo"]
    )

    assert launcher._run_index() == 0

    records = list_repo_records()
    assert len(records) == 1
    assert records[0]["alias"] == "cli-demo"
    assert records[0]["active_snapshot_status"] == "succeeded"

    discovered = mcp_tools.list_repositories()
    assert discovered["status"] == "ok"
    data = discovered["data"]
    assert data["indexed_count"] == 1
    assert data["repositories"][0]["alias"] == "cli-demo"
    assert data["repositories"][0]["indexed"] is True


def test_index_mode_is_idempotent_on_second_run(tmp_path: Path, monkeypatch) -> None:
    """同一仓库重复建索引复用 repo_id，而不是生成重复仓库。"""
    repo = tmp_path / "cli-repo-idem"
    repo.mkdir()
    _git(repo, "init")
    (repo / "app.py").write_text("def hello():\n    return 'hi'\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "-c", "user.name=T", "-c", "user.email=t@t", "commit", "-m", "initial")

    monkeypatch.setattr(
        sys, "argv", ["repomind-backend.exe", "--index", "--repo", str(repo), "--alias", "cli-demo"]
    )
    assert launcher._run_index() == 0
    records_after_first = list_repo_records()
    assert len(records_after_first) == 1

    assert launcher._run_index() == 0
    records_after_second = list_repo_records()
    assert len(records_after_second) == 1
    assert records_after_second[0]["id"] == records_after_first[0]["id"]


def test_index_mode_missing_repo_arg_returns_usage_error(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["repomind-backend.exe", "--index"])
    assert launcher._run_index() == 2


def test_index_mode_invalid_repo_path_returns_error(tmp_path: Path, monkeypatch) -> None:
    missing = tmp_path / "does-not-exist"
    monkeypatch.setattr(sys, "argv", ["repomind-backend.exe", "--index", "--repo", str(missing)])
    assert launcher._run_index() == 1


def test_mcp_mode_consumes_launcher_flag_and_preserves_profile(
    monkeypatch,
) -> None:
    received_argv: list[str] = []

    def fake_mcp_main() -> None:
        received_argv.extend(sys.argv)

    monkeypatch.setattr(mcp_entry, "main", fake_mcp_main)
    original_argv = ["repomind-backend.exe", "--mcp", "--profile", "coding-agent"]
    monkeypatch.setattr(sys, "argv", original_argv.copy())

    launcher.main()

    assert received_argv == ["repomind-backend.exe", "--profile", "coding-agent"]
    assert sys.argv == original_argv


def test_without_mcp_flag_starts_http_server(monkeypatch) -> None:
    started = False

    def fake_http_main() -> None:
        nonlocal started
        started = True

    monkeypatch.setattr(sys, "argv", ["repomind-backend.exe"])
    monkeypatch.setattr("service.main.main", fake_http_main)

    launcher.main()

    assert started is True
