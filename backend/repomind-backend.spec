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
# 阶段 A2：把确定性预建 demo 索引（repomind.sqlite3 + index.marker）注入 one-file exe。
# one-file 模式启动时解压到 sys._MEIPASS/index/；MCP server 检测到 marker 后
# 用只读 URI 直接读取该索引，实现"开箱即查 demo"。构建脚本：scripts/build_prebuilt_index.ps1。
prebuilt_index_root = backend_root / "resources" / "prebuilt"
# index.marker 入库，repomind.sqlite3 被 *.sqlite3 规则忽略、由
# scripts/build_prebuilt_index.ps1 在打包前重新生成；只有两者都存在时才注入 datas，
# 避免新 clone 只有 marker、没有 sqlite 时把不存在的文件写进 datas。
if (prebuilt_index_root / "index.marker").exists() and (prebuilt_index_root / "repomind.sqlite3").exists():
    datas += [(str(prebuilt_index_root / "repomind.sqlite3"), "index")]
    datas += [(str(prebuilt_index_root / "index.marker"), "index")]
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

# 排除可选的重型 ML 依赖，保证打包体积与干净环境（CI：requirements-build.txt）一致。
# service/core/retrieval/reranker.py 只在用户把 reranker_provider 设为 flag_embedding 时才
# 在函数内部 import FlagEmbedding；这个 provider 默认 disabled，且 available() 会捕获
# ImportError 优雅降级为基线检索。PyInstaller 静态分析会把整棵 FlagEmbedding ->
# torch / transformers / datasets / accelerate 依赖树打进去（本地 fat Python 环境会因此
# 让 exe 膨胀到 ~300MB）。显式 excludes 后无论构建机装了什么都能稳定产出 ~47MB
# （含 numpy+OpenBLAS、cryptography、Pillow 与 Python 运行时，属标准传递依赖）。
# numpy 是 requirements.txt 声明的直接运行时依赖（service/core/vector_store.py），保留。
excludes = [
    "FlagEmbedding",
    "torch",
    "torchvision",
    "torchaudio",
    "transformers",
    "datasets",
    "accelerate",
    "safetensors",
    "tokenizers",
    "hf_xet",
    "huggingface_hub",
    "sentence_transformers",
    "scipy",
    "pyarrow",
    "pandas",
    "matplotlib",
    "sklearn",
    "IPython",
    "jedi",
    "sympy",
]

a = Analysis(
    [str(backend_root / "service" / "launcher.py")],
    pathex=[str(backend_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
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
