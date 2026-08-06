"""RepoMind MCP 一键注册脚本（源码用户用）。

用法：
    python scripts/setup_mcp.py               # 自动注册到 Claude Code + Codex
    python scripts/setup_mcp.py --dry-run     # 只打印将要写入什么，不改任何文件
    python scripts/setup_mcp.py --data-dir <目录>   # 让 MCP 指向指定数据目录里的索引
    python scripts/setup_mcp.py --force       # 已存在 repomind 条目时也覆盖更新

它会写入三个文件（全部 merge、先写 .bak、原子写，绝不整表覆盖）：
  %USERPROFILE%\\.claude.json          顶层 mcpServers.repomind（stdio）
  %USERPROFILE%\\.claude\\settings.json  permissions.allow += "mcp__repomind__*"
  %USERPROFILE%\\.codex\\config.toml     [mcp_servers.repomind]

为什么不能直接复制粘贴官方 CLI 命令：
  Windows 上 `claude mcp add <name> -- cmd /c ...` 会把 `/c` 改写成 `C:/`；
  直接写配置文件最可靠。MCP server 只在会话启动时加载，改完后必须重开会话。
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

# 顶层模块名。放在脚本顶部方便读者先看到"这个脚本到底写哪三个文件"。
CLAUDE_MCP_SERVER_NAME = "repomind"


def _repo_root() -> Path:
    """脚本位于 <repo>/scripts/ 下，向上两级就是仓库根目录。"""
    return Path(__file__).resolve().parent.parent


def _resolve_command(data_dir: str | None) -> dict:
    """决定 MCP 用哪个命令启动后端。

    优先使用已打包的 exe（backend-dist/repomind-backend.exe），因为它自包含、
    不需要 Python；源码环境则用当前 Python 运行 `python -m service.mcp_server`，
    并通过 PYTHONPATH 指向 backend 目录，保证不依赖启动时的工作目录。
    """
    backend_exe = _repo_root() / "backend-dist" / "repomind-backend.exe"
    env: dict[str, str] = {"PYTHONIOENCODING": "utf-8"}
    if data_dir:
        data_path = Path(data_dir).expanduser().resolve()
        env["REPOMIND_PATHS__DATA_DIR"] = str(data_path)
        env["REPOMIND_PATHS__DATABASE_PATH"] = str(data_path / "repomind.sqlite3")
    if backend_exe.exists():
        return {"command": str(backend_exe), "args": ["--mcp"], "env": env}
    backend_dir = _repo_root() / "backend"
    env["PYTHONPATH"] = str(backend_dir)
    return {"command": sys.executable, "args": ["-m", "service.mcp_server"], "env": env}


def _load_json(path: Path) -> dict:
    """读取 JSON 文件；文件不存在时返回空 dict，保证后面 merge 统一处理。"""
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        value = json.load(f)
    if not isinstance(value, dict):
        raise ValueError(f"{path} 不是 JSON 对象，拒绝改写该文件")
    return value


def _atomic_write_json(path: Path, data: dict) -> None:
    """把 dict 写入 JSON 文件：先写同目录临时文件再 rename，避免写一半损坏。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def _backup(path: Path) -> None:
    """写之前备份原文件为 .bak-<时间戳>，防止脚本 bug 或并发把配置写坏。"""
    if not path.exists():
        return
    backup_path = path.parent / f"{path.name}.bak-{_timestamp()}"
    shutil.copy2(path, backup_path)
    print(f"  已备份原文件 -> {backup_path}")


def _timestamp() -> str:
    import datetime
    return datetime.datetime.now().strftime("%Y%m%dT%H%M%S")


def _merge_claude_json(entry: dict, *, dry_run: bool, force: bool) -> bool:
    """把 repomind 合并进 %USERPROFILE%\\.claude.json 的顶层 mcpServers。"""
    path = Path.home() / ".claude.json"
    if dry_run:
        print(f"[dry-run] 将写入 {path}")
        return True
    data = _load_json(path)
    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise ValueError(".claude.json 的 mcpServers 不是对象，请人工检查后重试")
    if CLAUDE_MCP_SERVER_NAME in servers and not force:
        print(f"  跳过：{path} 已存在 mcpServers.{CLAUDE_MCP_SERVER_NAME}（用 --force 覆盖）")
        return False
    if CLAUDE_MCP_SERVER_NAME not in servers:
        _backup(path)
    servers[CLAUDE_MCP_SERVER_NAME] = entry
    _atomic_write_json(path, data)
    print(f"  已写入 {path} 的 mcpServers.{CLAUDE_MCP_SERVER_NAME}")
    return True


def _merge_claude_settings(*, dry_run: bool, force: bool) -> bool:
    """往 %USERPROFILE%\\.claude\\settings.json 的 permissions.allow 追加自动放行。"""
    path = Path.home() / ".claude" / "settings.json"
    allow_entry = "mcp__repomind__*"
    if dry_run:
        print(f"[dry-run] 将写入 {path} 的 permissions.allow += {allow_entry!r}")
        return True
    data = _load_json(path)
    permissions = data.setdefault("permissions", {})
    if not isinstance(permissions, dict):
        raise ValueError(".claude/settings.json 的 permissions 不是对象，请人工检查后重试")
    allow = permissions.setdefault("allow", [])
    if not isinstance(allow, list):
        raise ValueError(".claude/settings.json 的 permissions.allow 不是数组，请人工检查后重试")
    if allow_entry in allow and not force:
        print(f"  跳过：{path} 的 permissions.allow 已包含 {allow_entry}")
        return False
    if allow_entry not in allow:
        _backup(path)
        allow.append(allow_entry)
        _atomic_write_json(path, data)
    print(f"  已写入 {path} 的 permissions.allow += {allow_entry}")
    return True


def _toml_quote(value: str) -> str:
    """把字符串转成 TOML 字符串字面量：转义反斜杠与双引号。"""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _format_codex_section(command: str, args: list[str], env: dict[str, str]) -> str:
    """生成 Codex config.toml 里的 [mcp_servers.repomind] 片段。"""
    arg_items = ", ".join(_toml_quote(a) for a in args)
    env_items = ", ".join(f"{_toml_quote(k)} = {_toml_quote(v)}" for k, v in sorted(env.items()))
    # required 固定为 false：server 挂了不能把 Codex 一起拖垮。
    return (
        "[mcp_servers.repomind]\n"
        f"command = {_toml_quote(command)}\n"
        f"args = [{arg_items}]\n"
        f"env = {{ {env_items} }}\n"
        "default_tools_approval_mode = \"auto\"\n"
        "enabled = true\n"
        "required = false\n"
    )


def _replace_toml_section(lines: list[str], section: str) -> list[str]:
    """用正则查找 [section] 起、到下一个 [ 节为止的行区间，并删除之。"""
    import re
    start = None
    for i, line in enumerate(lines):
        if re.match(r"^\s*\[" + re.escape(section) + r"\]\s*$", line):
            start = i
            break
    if start is None:
        return lines
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if re.match(r"^\s*\[", lines[i]):
            end = i
            break
    return lines[:start] + lines[end:]


def _merge_codex_config(command: str, args: list[str], env: dict[str, str],
                        *, dry_run: bool, force: bool) -> bool:
    """把 [mcp_servers.repomind] 追加进 %USERPROFILE%\\.codex\\config.toml。

    用文本追加而不是 tomllib 整文件重写，避免格式化破坏用户已有配置和注释。
    """
    path = Path.home() / ".codex" / "config.toml"
    section = "mcp_servers.repomind"
    if dry_run:
        print(f"[dry-run] 将写入 {path} 的 [{section}]")
        return True
    lines: list[str] = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    import re
    exists = any(re.match(r"^\s*\[" + re.escape(section) + r"\]\s*$", line) for line in lines)
    if exists and not force:
        print(f"  跳过：{path} 已存在 [{section}]（用 --force 覆盖）")
        return False
    _backup(path)
    if exists:
        lines = _replace_toml_section(lines, section)
    block = _format_codex_section(command, args, env)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    lines.append("\n" + block)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(lines), encoding="utf-8")
    print(f"  已写入 {path} 的 [{section}]")
    return True


def _validate(dry_run: bool) -> None:
    """尽力校验注册结果；CLI 不在 PATH 时跳过，不影响脚本成功。"""
    if dry_run:
        return
    for name in ("claude", "codex"):
        if shutil.which(name):
            print(f"  检测到 {name} CLI，尝试校验……")
            if name == "claude":
                os.system(f"{name} mcp get repomind")
            else:
                os.system(f"{name} mcp list")
        else:
            print(f"  未检测到 {name} CLI（跳过校验；它不在 PATH 不影响 MCP 配置生效）")


def main() -> int:
    parser = argparse.ArgumentParser(description="RepoMind MCP 一键注册")
    parser.add_argument("--dry-run", action="store_true", help="只打印将要写入什么，不改文件")
    parser.add_argument("--data-dir", help="MCP 读取该目录下的 repomind.sqlite3 索引")
    parser.add_argument("--force", action="store_true", help="已存在 repomind 条目时也覆盖更新")
    args = parser.parse_args()

    entry = _resolve_command(args.data_dir)
    command_desc = entry["command"] if "backend-dist" in entry["command"] else f"{entry['command']} {' '.join(entry['args'])}"
    print(f"将注册 RepoMind MCP：command = {command_desc}")
    if args.data_dir:
        print(f"  数据目录 = {Path(args.data_dir).expanduser().resolve()}")

    _merge_claude_json(entry, dry_run=args.dry_run, force=args.force)
    _merge_claude_settings(dry_run=args.dry_run, force=args.force)
    _merge_codex_config(entry["command"], entry["args"], entry["env"],
                        dry_run=args.dry_run, force=args.force)
    _validate(args.dry_run)

    print("完成。请重启 Claude Code / Codex 会话后生效（MCP server 只在会话启动时加载）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
