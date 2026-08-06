"""
这个文件负责 MCP Server 的 stdio 启动入口。
启动方式：python -m service.mcp_server
MCP 层只做参数转发和结果返回，所有实际逻辑都在 service.mcp_server.tools 里调用现成核心模块完成。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP


def _apply_prebuilt_index_if_present() -> None:
    """检测捆绑在冻结 exe 里的预建 demo 索引，并让 MCP 只读地使用它。

    必须在任何 get_settings() 调用之前运行。one-file 模式启动时会把预建索引解压到
    sys._MEIPASS/index/；只要存在 index.marker，就把数据库路径指向它并默认
    sqlite_read_only，避免迁移/WAL/遥测写坏捆绑索引。
    用户（或 smoke）显式设置了 REPOMIND_PATHS__DATABASE_PATH 时保持其设置，
    也不额外强制只读——预建索引只读只适用于"我们接管默认路径"的场景。
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return
    index_dir = Path(meipass) / "index"
    if not (index_dir / "index.marker").exists():
        return
    if "REPOMIND_PATHS__DATABASE_PATH" not in os.environ:
        os.environ["REPOMIND_PATHS__DATABASE_PATH"] = str(index_dir / "repomind.sqlite3")
        os.environ["REPOMIND_PATHS__DATA_DIR"] = str(index_dir)
        if "REPOMIND_SQLITE_READ_ONLY" not in os.environ:
            os.environ["REPOMIND_SQLITE_READ_ONLY"] = "true"


_apply_prebuilt_index_if_present()

from service.mcp_server import tools as impl

mcp = FastMCP(
    name="repomind",
    instructions=(
        "Pass the user's original wording as question. After locate_code returns, always continue to a final answer; the result is navigation evidence rather than source text, so do not invent unreturned behavior. "
        "Prefer rank=1 or is_primary=true when it answers the question. "
        "For example, ask locate_code with question='Where is authenticate defined?' and limit=3 before answering. "
        "For natural-language code-location questions, unknown symbols, cross-file behavior, or questions that need multiple locations, call locate_code once first with compact=true. The first candidate is the highest-ranked candidate; prefer it when it answers the question, and treat is_primary=true as the preferred candidate. Report multiple independent locations separately without merging ranges. "
        "Use get_symbol only when you already know the exact function, class, or qualified symbol name. "
        "Use search_code only when you need supporting snippets beyond the candidate locations. "
        "In your final answer, report every independently relevant location as PATH:START_LINE-END_LINE on its own line; do not merge separate locations into one broad file range. Compact results include rank, is_primary, symbol, kind, and match_basis; use these signals before requesting detailed evidence. "
        "RepoMind 是一个只读的代码上下文服务，供 Claude Code/Codex 等编码 Agent 查询已索引仓库。"
        "它不会执行目标仓库代码、不会修改文件、不会安装依赖。"
        "先调用 list_repositories 发现可用 repo_id 和索引状态；其他工具都需要显式的 repo_id。"
        "未显式提供 snapshot_id 时，默认使用该仓库当前 active 的 succeeded 快照。"
        "返回结果统一包含 repo_id/snapshot_id/commit/status/data/evidence/limitations 字段。"
        "search_code 返回 not_found 时表示没有可验证证据，外部 Agent 不应据此推断代码事实。"
    ),
)

coding_agent_mcp = FastMCP(
    name="repomind-coding-agent",
    instructions=(
        "This server is bound to one indexed repository snapshot and exposes only concise code navigation. "
        "For every natural-language location, behavior, unknown-symbol, or cross-file question, pass the user's original wording to locate_code first. "
        "After the tool returns, always produce a final answer; prefer rank=1 or is_primary=true, and never invent source details that were not returned. "
        "When status is not_found, state that the indexed snapshot did not return a verified location. "
        "For a code-location question, call locate_code once and answer directly from its returned ranked PATH:START_LINE-END_LINE locations. The first candidate is the current strongest candidate and is_primary=true marks it as preferred. Keep multiple independent locations separate. "
        "Do not call another discovery tool. The result contains no source text; only request detailed code evidence when compact fields are insufficient."
    ),
)

coding_agent_location_1_mcp = FastMCP(
    name="repomind-coding-agent-location-1",
    instructions=(
        "This server is bound to one indexed repository snapshot and exposes only concise code navigation. "
        "For every single-location natural-language question, pass the user's original wording to locate_code first. "
        "After the tool returns, always produce a final PATH:START_LINE-END_LINE answer; do not stop at the tool call or invent source details. "
        "When no verified location is returned, state that explicitly. "
        "For a single-location code question, call locate_code once; it returns the current strongest candidate. "
        "Answer directly from the returned PATH:START_LINE-END_LINE location and always produce a final answer after the tool result. "
        "Do not call another discovery tool."
    ),
)

coding_agent_context_mcp = FastMCP(
    name="repomind-coding-agent-context",
    instructions=(
        "This server is bound to one indexed repository snapshot and provides concise navigation plus budgeted source evidence for complex coding questions. "
        "Pass the user's original wording to locate_code first for every natural-language location, behavior, unknown-symbol, or cross-file question. "
        "For a simple location request, answer from locate_code and do not request more context. "
        "Call get_code_context at most once only when the user needs implementation details, cross-file behavior, change impact, or supporting source evidence. "
        "After either tool returns, always produce a final answer. Prefer rank=1 or is_primary=true, and distinguish returned source evidence from inferences. "
        "When status is not_found, state that the indexed snapshot did not return verified evidence; never invent source details. "
        "If get_code_context includes recommended_follow_up, follow that reading order before asking for any more context. "
        "This is a read-only service. The context tool returns a deliberately small, token-budgeted evidence set rather than complete files."
    ),
)

def _bound_agent_target() -> tuple[str, str | None]:
    """Read the isolated benchmark target without exposing it in the tool schema."""
    repo_id = os.environ.get("REPOMIND_MCP_REPO_ID", "").strip()
    snapshot_id = os.environ.get("REPOMIND_MCP_SNAPSHOT_ID", "").strip() or None
    if not repo_id:
        raise ValueError(
            "coding-agent MCP profile requires REPOMIND_MCP_REPO_ID in the server environment."
        )
    return repo_id, snapshot_id


@coding_agent_mcp.tool()
def locate_code(question: str, limit: int | None = None) -> dict:
    """Return answer-ready code locations for the bound repository snapshot.

    Call this once for a natural-language location, behavior, symbol, or cross-file
    question. The response intentionally contains only snapshot proof and narrow
    path/line ranges, so it can be used directly in a coding-agent answer.
    """
    try:
        repo_id, snapshot_id = _bound_agent_target()
    except ValueError as exc:
        return {
            "status": "error",
            "locations": [],
            "limitations": [str(exc)],
        }
    return impl.locate_code(repo_id, question, snapshot_id, limit, compact=True)


@coding_agent_location_1_mcp.tool(name="locate_code")
def locate_code_location_1(question: str, limit: int | None = None) -> dict:
    """Return only the strongest answer-ready code location.

    This is an explicitly separate experimental profile for single-location
    navigation. The default is one location even when the client omits limit.
    """
    try:
        repo_id, snapshot_id = _bound_agent_target()
    except ValueError as exc:
        return {
            "status": "error",
            "locations": [],
            "limitations": [str(exc)],
        }
    requested_limit = 1 if limit is None else min(limit, 1)
    result = impl.locate_code(repo_id, question, snapshot_id, requested_limit, compact=True)
    # Preserve this profile's original minimal contract. The richer candidate
    # signals belong to the multi-location coding-agent profile and would
    # otherwise change the single-location benchmark variable.
    if isinstance(result, dict) and isinstance(result.get("locations"), list):
        result["locations"] = [
            {
                "path": item.get("path"),
                "start_line": item.get("start_line"),
                "end_line": item.get("end_line"),
            }
            for item in result["locations"]
            if isinstance(item, dict)
        ]
    return result


@coding_agent_context_mcp.tool(name="locate_code")
def locate_code_context(question: str, limit: int | None = None) -> dict:
    """Return compact, answer-ready locations for the bound repository snapshot.

    Use this first for location, behavior, symbol, and cross-file questions. For
    simple location requests, answer from this result without calling
    ``get_code_context``.
    """
    try:
        repo_id, snapshot_id = _bound_agent_target()
    except ValueError as exc:
        return {
            "status": "error",
            "locations": [],
            "limitations": [str(exc)],
        }
    return impl.locate_code(repo_id, question, snapshot_id, limit, compact=True)


@coding_agent_context_mcp.tool()
def get_code_context(question: str, limit: int | None = None) -> dict:
    """Return a small, read-only source-evidence set for a complex question.

    Call only after ``locate_code`` when compact paths and lines are insufficient
    to explain implementation behavior, cross-file flow, or likely change impact.
    The result is token-budgeted and never includes an entire repository or file.
    """
    try:
        repo_id, snapshot_id = _bound_agent_target()
    except ValueError as exc:
        return {
            "status": "error",
            "evidence": [],
            "limitations": [str(exc)],
        }
    requested_limit = 4 if limit is None else min(limit, 4)
    return impl.get_code_context(repo_id, question, snapshot_id, requested_limit)


@mcp.tool()
def list_repositories(limit: int | None = None) -> dict:
    """列出当前 RepoMind 数据库中的仓库、repo_id 和活动 Snapshot，供后续工具选择目标；不返回本机绝对路径。

    Args:
        limit: 可选，返回仓库数量上限（默认和最大值均为 100）。
    """
    return impl.list_repositories(limit)


@mcp.tool()
def repo_overview(repo_id: str, snapshot_id: str | None = None) -> dict:
    """获取仓库概览：别名、commit、快照 ID、文件统计、推荐阅读顺序。只读索引结果，不代表工作区未提交改动。

    Args:
        repo_id: RepoMind 中已注册仓库的 ID。
        snapshot_id: 可选，指定要查询的快照 ID；必须属于 repo_id 且状态为 succeeded。省略时使用该仓库当前 active 快照。
    """
    return impl.repo_overview(repo_id, snapshot_id)


@mcp.tool()
def search_code(repo_id: str, query: str, snapshot_id: str | None = None, limit: int | None = None) -> dict:
    """在已索引仓库中做混合检索（关键词+可选语义），返回带文件路径/行号/证据 ID 的代码片段，而不是整份文件。没有证据时返回 not_found，不能据此推断代码事实。

    Args:
        repo_id: RepoMind 中已注册仓库的 ID。
        query: 检索关键词或问题描述。
        snapshot_id: 可选，指定要查询的快照 ID；省略时使用该仓库当前 active 快照。
        limit: 可选，返回证据条数上限（默认 6，最大 20）。
    """
    return impl.search_code(repo_id, query, snapshot_id, limit)


@mcp.tool()
def locate_code(
    repo_id: str,
    question: str,
    snapshot_id: str | None = None,
    limit: int | None = None,
    compact: bool = False,
) -> dict:
    """Locate one or more code locations for a natural-language question.

    Prefer this tool when the symbol name is unknown, the behavior crosses files, or the final
    answer needs multiple independent locations. It returns compact candidate locations with
    file paths and line ranges. Use get_symbol only for a known exact symbol name.
    Args:
        repo_id: Indexed repository ID from list_repositories.
        question: Natural-language behavior, responsibility, or code-location question.
        snapshot_id: Optional succeeded snapshot ID for this repository.
        limit: Optional candidate-location limit (default 6, maximum 12).
        compact: Return only answer-ready path and line locations for a coding agent. Use true
            for ordinary location questions; use false only when evidence IDs and explanations
            are required for a human-facing audit.
    """
    return impl.locate_code(repo_id, question, snapshot_id, limit, compact)


@mcp.tool()
def get_symbol(repo_id: str, symbol_query: str, snapshot_id: str | None = None) -> dict:
    """按名称或限定名查询符号定义和关系；若存在多个同名符号，返回候选列表并说明匹配方式。

    Args:
        repo_id: RepoMind 中已注册仓库的 ID。
        symbol_query: 符号名称或限定名，例如 "UserService.create" 或 "create_user"。
        snapshot_id: 可选，指定要查询的快照 ID；省略时使用该仓库当前 active 快照。
    """
    return impl.get_symbol(repo_id, symbol_query, snapshot_id)


@mcp.tool()
def analyze_impact(repo_id: str, symbol_query: str, snapshot_id: str | None = None) -> dict:
    """静态影响分析：给出目标符号定义、已解析的调用关系、仅有源码支撑的引用候选、涉及的测试文件候选。
    明确区分"已解析关系"和"仅引用候选"；不能覆盖动态调用/反射/无法确定类型的实例调用。

    Args:
        repo_id: RepoMind 中已注册仓库的 ID。
        symbol_query: 目标符号名称或限定名。
        snapshot_id: 可选，指定要查询的快照 ID；省略时使用该仓库当前 active 快照。
    """
    return impl.analyze_impact(repo_id, symbol_query, snapshot_id)


@mcp.tool()
def find_related_tests(repo_id: str, symbol_query: str | None = None, snapshot_id: str | None = None) -> dict:
    """定位测试/构建/入口文件候选。只做定位，绝不执行目标仓库的任何测试或代码。

    Args:
        repo_id: RepoMind 中已注册仓库的 ID。
        symbol_query: 可选，目标符号名称；提供时会尝试关联到具体测试文件，不提供则返回全部测试/构建/入口文件候选（未做筛选）。
        snapshot_id: 可选，指定要查询的快照 ID；省略时使用该仓库当前 active 快照。
    """
    return impl.find_related_tests(repo_id, symbol_query, snapshot_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the RepoMind read-only MCP server.")
    parser.add_argument(
        "--profile",
        choices=("full", "coding-agent", "coding-agent-location-1", "coding-agent-context"),
        default="full",
        help="Expose the complete read-only API, compact locator, or bound budgeted-context profile.",
    )
    args = parser.parse_args()
    if args.profile == "coding-agent-location-1":
        server = coding_agent_location_1_mcp
    elif args.profile == "coding-agent-context":
        server = coding_agent_context_mcp
    else:
        server = coding_agent_mcp if args.profile == "coding-agent" else mcp
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
