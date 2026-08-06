"""Select the HTTP, stdio MCP, or CLI index runtime before importing either service."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import time


def _print_index_progress(progress: float, message: str | None = None) -> None:
    """把 ingest 的进度回调转成一行一行刷新的百分比提示，方便用户看到"还在干活"而不是卡死。"""
    text = message or "正在建索引"
    print(f"[{int(progress * 100):3d}%] {text}", flush=True)


def _run_index() -> int:
    """`--index` 分支：命令行同步建立仓库索引，最后打印 repo_id 与耗时。"""
    args = sys.argv[1:]
    if "--repo" not in args:
        print("用法：repomind-backend --index --repo <git路径> --data-dir <目录> [--alias <名称>]")
        return 2

    def _value(flag: str) -> str | None:
        if flag not in args:
            return None
        index = args.index(flag)
        if index + 1 >= len(args):
            return None
        return args[index + 1]

    repo_arg = _value("--repo")
    data_dir = _value("--data-dir")
    alias = _value("--alias")
    if not repo_arg:
        print("--repo 参数不能为空。")
        return 2

    # 必须在第一次 get_settings() 之前把数据目录写进环境变量，
    # 这样底层 SQLite 连接会写到用户指定的目录，而不是默认的 ~/.repomind。
    if data_dir:
        data_dir_path = Path(data_dir).expanduser()
        os.environ["REPOMIND_PATHS__DATA_DIR"] = str(data_dir_path)
        os.environ["REPOMIND_PATHS__DATABASE_PATH"] = str(data_dir_path / "repomind.sqlite3")

    from service.core.repo_scanner import (
        RepositoryScanError,
        get_current_branch,
        get_current_commit,
        resolve_repository_path,
        validate_git_repository,
    )
    from service.storage.repository_store import create_repo_record, find_repo_by_source

    try:
        repo_path = resolve_repository_path(repo_arg)
        validate_git_repository(repo_path)
    except RepositoryScanError as exc:
        print(f"仓库校验失败：{exc}")
        return 1

    branch = get_current_branch(repo_path)
    current_commit = get_current_commit(repo_path)
    if not current_commit:
        print("仓库还没有任何 commit，无法建立索引。")
        return 1

    # 复用 create_repository 的幂等逻辑：同一路径重复建索引时复用已有 repo_id。
    existing = find_repo_by_source(repo_path, None)
    if existing is not None:
        repo_id = existing["id"]
        print(f"仓库已注册，复用 repo_id={repo_id}")
    else:
        repo_id = create_repo_record(
            repo_path=repo_path,
            alias=alias or repo_path.name,
            remote_url=None,
            branch=branch,
            current_commit=current_commit,
        )

    from service.core.ingest_service import ingest_repository_snapshot

    # 对照报告 §1.4：先告知预计耗时，避免用户以为程序卡死。
    print("首次建索引耗时参考：词法索引 10 文件约 1.5 秒、196 文件约 61 秒；启用 embedding 为分钟级。")
    print("建索引是后续检索的前提，首次完成后查询会直接复用本索引。")
    print("正在建索引，请不要中断……")

    started = time.monotonic()
    try:
        result = ingest_repository_snapshot(repo_id, progress_callback=_print_index_progress)
    except (RepositoryScanError, RuntimeError, ValueError) as exc:
        print(f"建索引失败：{exc}")
        return 1

    elapsed = time.monotonic() - started
    print(f"索引完成：repo_id={result.repo_id}，snapshot_id={result.snapshot_id}，"
          f"commit={result.commit_hash[:12]}，文件 {result.indexed_file_count} 个，"
          f"chunk {result.chunk_count} 条，实际耗时 {elapsed:.1f} 秒")
    print("索引已建立。后续查询请直接复用本数据目录，不需要重新建索引。")
    return 0


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

    if "--index" in sys.argv[1:]:
        raise SystemExit(_run_index())

    from service.main import main as run_http_server

    run_http_server()


if __name__ == "__main__":
    main()
