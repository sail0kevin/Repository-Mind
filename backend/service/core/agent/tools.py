"""Main Agent 可调用的只读 Specialist Tools。"""
from __future__ import annotations

from service.core.agent.models import AgentContext, ToolDecision, ToolResult
from service.core.codegraph.store import get_call_chain, search_graph_nodes
from service.storage.catalog_store import list_catalog_items
from service.storage.evidence_store import list_evidence_units, list_relations, list_symbols
from service.storage.repository_store import list_file_records


def _term(question: str) -> str:
    """提取可用于符号查询的最后一个较长词，提取不到就使用完整问题。"""
    words = [item.strip("，。？！,.?!()[]{}:：`'\"") for item in question.split()]
    candidates = [item for item in words if len(item) >= 2]
    return candidates[-1] if candidates else question[:80]


def repository_navigator(context: AgentContext) -> ToolResult:
    """返回 Overview、Reading Guide 和入口文件。"""
    items = list_catalog_items(context.repo_id, context.snapshot_id)
    selected = [item for item in items if item["kind"] in {"repository_overview", "reading_guide", "subsystem"}]
    evidence = []
    for item in selected:
        evidence.extend({"chunk_id": evidence_id, "file_path": item.get("path") or "repository",
                         "start_line": None, "end_line": None, "reason": "Catalog 来源"}
                        for evidence_id in item.get("source_evidence_ids", [])[:4])
    summary = "；".join(item["summary"] for item in selected[:5]) or "当前快照没有 Catalog 卡片。"
    return ToolResult("repository_navigator", summary, evidence, {"items": selected[:12]})


def language_structure(context: AgentContext) -> ToolResult:
    """查询相关符号及其关系。"""
    query = _term(context.question)
    symbols = list_symbols(context.repo_id, context.snapshot_id, query=query, limit=20)
    relations = list_relations(context.repo_id, context.snapshot_id, limit=1000)
    symbol_ids = {item["id"] for item in symbols}
    related = [item for item in relations if item.get("source_symbol_id") in symbol_ids or item.get("target_symbol_id") in symbol_ids]
    evidence = [{"chunk_id": item.get("evidence_id") or "", "file_path": item.get("file_path") or "",
                 "start_line": item.get("start_line"), "end_line": item.get("end_line"),
                 "reason": "符号结构"} for item in symbols]
    return ToolResult("language_structure", f"找到 {len(symbols)} 个相关符号和 {len(related)} 条关系。",
                      evidence, {"symbols": symbols, "relations": related[:100]})


def dependency_impact(context: AgentContext) -> ToolResult:
    """从图谱与规范关系两侧分析一跳影响。"""
    query = _term(context.question)
    nodes = search_graph_nodes(context.repo_id, query, limit=10, snapshot_id=context.snapshot_id)
    chain = get_call_chain(context.repo_id, query, "both", 2, context.snapshot_id)
    relations = list_relations(context.repo_id, context.snapshot_id, limit=2000)
    evidence = [{"chunk_id": "", "file_path": item.get("file_path") or "",
                 "start_line": item.get("start_line"), "end_line": item.get("end_line"),
                 "reason": "代码图谱影响"} for item in nodes]
    return ToolResult("dependency_impact",
                      f"图谱命中 {len(nodes)} 个节点，调用链包含 {len(chain.get('nodes', []))} 个节点。",
                      evidence, {"nodes": nodes, "call_chain": chain, "relation_count": len(relations)})


def test_runtime(context: AgentContext) -> ToolResult:
    """只读定位测试、构建和入口文件，不执行目标仓库。"""
    files = list_file_records(context.repo_id, limit=10000, snapshot_id=context.snapshot_id)
    selected = [item for item in files if item.get("is_test_file") or any(
        token in item["relative_path"].casefold() for token in ("test", "spec", "package.json", "pyproject", "requirements", "main", "app")
    )]
    evidence = [{"chunk_id": "", "file_path": item["relative_path"], "start_line": None,
                 "end_line": None, "reason": "测试/运行文件"} for item in selected[:30]]
    return ToolResult("test_runtime", f"定位到 {len(selected)} 个测试、构建或入口相关文件。",
                      evidence, {"files": selected[:50]}, limitation="按安全边界未执行被分析仓库。")


def security_review(context: AgentContext) -> ToolResult:
    """基于已持久化 Evidence 做规则安全线索扫描，不重新读取工作树。"""
    evidence_rows = list_evidence_units(context.repo_id, context.snapshot_id, limit=10000)
    patterns = {
        "动态执行": ("eval(", "exec("),
        "命令执行": ("shell=true", "subprocess."),
        "敏感字段": ("api_key", "password", "private key", "secret"),
        "不安全反序列化": ("pickle.loads", "yaml.load("),
    }
    findings = []
    evidence = []
    for row in evidence_rows:
        text = str(row.get("content") or "").casefold()
        matched = [title for title, terms in patterns.items() if any(term in text for term in terms)]
        if not matched:
            continue
        findings.append({"file_path": row.get("file_path"), "start_line": row.get("start_line"),
                         "end_line": row.get("end_line"), "rules": matched})
        evidence.append({"chunk_id": row["id"], "file_path": row.get("file_path") or "",
                         "start_line": row.get("start_line"), "end_line": row.get("end_line"),
                         "reason": "安全规则命中"})
    return ToolResult("security_review", f"规则扫描发现 {len(findings)} 条需要人工确认的安全线索。",
                      evidence[:50], {"findings": findings[:50]},
                      limitation="静态规则扫描不是完整安全审计，也不会执行仓库代码。")


TOOLS = {
    "repository_navigator": repository_navigator,
    "language_structure": language_structure,
    "dependency_impact": dependency_impact,
    "test_runtime": test_runtime,
    "security_review": security_review,
}


def run_tool(decision: ToolDecision, context: AgentContext) -> ToolResult:
    """只允许调用显式注册的只读工具。"""
    function = TOOLS.get(decision.name)
    if function is None:
        return ToolResult(decision.name, "工具不存在。", limitation="未知 Specialist Tool")
    return function(context)
