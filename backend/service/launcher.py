"""Select the HTTP or stdio MCP runtime before importing either service."""
from __future__ import annotations

import sys


def main() -> None:
    if "--mcp" in sys.argv[1:]:
        from service.mcp_server.__main__ import main as run_mcp_server

        original_argv = sys.argv
        sys.argv = [original_argv[0], *(arg for arg in original_argv[1:] if arg != "--mcp")]
        try:
            run_mcp_server()
        finally:
            sys.argv = original_argv
        return

    from service.main import main as run_http_server

    run_http_server()


if __name__ == "__main__":
    main()
