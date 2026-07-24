"""
这个文件负责 MCP Server 的 stdio 启动入口。
启动方式：python -m service.mcp_server
MCP 层只做参数转发和结果返回，所有实际逻辑都在 service.mcp_server.tools 里调用现成核心模块完成。
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from service.mcp_server import tools as impl

mcp = FastMCP(
    name="repomind",
    instructions=(
        "RepoMind 是一个只读的代码上下文服务，供 Claude Code/Codex 等编码 Agent 查询已索引仓库。"
        "它不会执行目标仓库代码、不会修改文件、不会安装依赖。"
        "先调用 list_repositories 发现可用 repo_id 和索引状态；其他工具都需要显式的 repo_id。"
        "未显式提供 snapshot_id 时，默认使用该仓库当前 active 的 succeeded 快照。"
        "返回结果统一包含 repo_id/snapshot_id/commit/status/data/evidence/limitations 字段。"
    ),
)


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
    """在已索引仓库中做混合检索（关键词+可选语义），返回带文件路径/行号/证据 ID 的代码片段，而不是整份文件。

    Args:
        repo_id: RepoMind 中已注册仓库的 ID。
        query: 检索关键词或问题描述。
        snapshot_id: 可选，指定要查询的快照 ID；省略时使用该仓库当前 active 快照。
        limit: 可选，返回证据条数上限（默认 10，最大 50）。
    """
    return impl.search_code(repo_id, query, snapshot_id, limit)


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
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
