from __future__ import annotations

import sys

from service import launcher
from service.mcp_server import __main__ as mcp_entry


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
