# RepoMind 后端正式 PyInstaller 配置。
# 所有路径都从本文件位置推导，避免依赖开发机目录或调用时的当前工作目录。
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs, collect_submodules

backend_root = Path(SPEC).resolve().parent

hiddenimports = [
    "service.main",
    "service.api",
    "service.api.v1",
    "service.config.settings",
    "service.storage.sqlite_db",
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
]
hiddenimports += collect_submodules("service.core.parsing")
hiddenimports += collect_submodules("service.storage.migrations")
hiddenimports += collect_submodules("service.mcp_server")

datas = []
binaries = []
# MCP SDK 包含按传输和消息类型动态导入的模块，冻结程序需要显式收集；
# mcp.cli 属于带 typer 的可选开发命令，不是 stdio Server 的运行依赖。
datas += collect_data_files("mcp")
binaries += collect_dynamic_libs("mcp")
hiddenimports += collect_submodules("mcp", filter=lambda name: not name.startswith("mcp.cli"))
# tree-sitter grammar 带有原生动态库，必须同时收集 Python 模块、数据和二进制文件。
for package_name in ("tree_sitter", "tree_sitter_javascript", "tree_sitter_typescript"):
    package_datas, package_binaries, package_hiddenimports = collect_all(package_name)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

a = Analysis(
    [str(backend_root / "service" / "launcher.py")],
    pathex=[str(backend_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="repomind-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)
