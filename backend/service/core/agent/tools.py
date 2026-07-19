"""Main Agent 可调用的只读 Specialist Tools。"""
from __future__ import annotations

import re

from service.core.agent.models import AgentContext, ToolDecision, ToolResult
from service.storage.catalog_store import list_catalog_items
from service.storage.evidence_store import (
    get_evidence_unit,
    list_evidence_units,
    list_relations,
    list_symbols,
)
from service.storage.repository_store import list_file_records


def _term(question: str) -> str:
    """提取可用于符号查询的最后一个较长词，提取不到就使用完整问题。"""
    words = [item.strip("，。？！,.?!()[]{}:：`'\"") for item in question.split()]
    candidates = [item for item in words if len(item) >= 2]
    return candidates[-1] if candidates else question[:80]


def _symbol_term(question: str) -> str:
    """优先提取限定名、snake_case 或 CamelCase 符号，排除问题尾部通用词。"""
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_.]*|[\u4e00-\u9fff]+", question)
    stopwords = {
        "what", "does", "which", "where", "when", "why", "how", "impact",
        "call", "calls", "caller", "callers", "chain", "tests", "test",
        "change", "changing", "affect", "affected", "will", "the",
    }
    symbol_candidates = [
        token for token in tokens
        if len(token) >= 3
        and token.casefold() not in stopwords
        and ("." in token or "_" in token or any(char.isupper() for char in token[1:]))
    ]
    if symbol_candidates:
        return max(symbol_candidates, key=len)
    ascii_identifiers = [
        token for token in tokens
        if token.isascii() and token.isidentifier() and len(token) >= 3
        and token.casefold() not in stopwords
    ]
    if ascii_identifiers:
        return max(ascii_identifiers, key=len)
    candidates = [token for token in tokens if len(token) >= 2 and token.casefold() not in stopwords]
    return candidates[-1] if candidates else _term(question)


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
    query = _symbol_term(context.question)
    symbols = list_symbols(context.repo_id, context.snapshot_id, query=query, limit=20)
    relations = list_relations(context.repo_id, context.snapshot_id, limit=1000)
    symbol_ids = {item["id"] for item in symbols}
    related = [item for item in relations if item.get("source_symbol_id") in symbol_ids or item.get("target_symbol_id") in symbol_ids]
    evidence = [{"chunk_id": item.get("evidence_id") or "", "file_path": item.get("file_path") or "",
                 "start_line": item.get("start_line"), "end_line": item.get("end_line"),
                 "reason": "符号结构"} for item in symbols]
    return ToolResult("language_structure", f"找到 {len(symbols)} 个相关符号和 {len(related)} 条关系。",
                      evidence, {"symbols": symbols, "relations": related[:100]})


def _hydrated_evidence(context: AgentContext, evidence_id: str | None, reason: str,
                       *, score: float, specialist_priority: int) -> dict | None:
    """将真实持久化 Evidence 转成可供最终综合使用的候选。"""
    if not evidence_id:
        return None
    row = get_evidence_unit(context.repo_id, evidence_id, context.snapshot_id)
    if not row or not str(row.get("file_path") or "").strip() or not str(row.get("content") or "").strip():
        return None
    return {
        **row,
        "chunk_id": row["id"],
        "reason": reason,
        "score": score,
        "specialist_priority": specialist_priority,
        "signals": ["specialist"],
    }


def _rank_target_symbols(symbols: list[dict], query: str) -> list[dict]:
    """优先精确限定名及其后缀，避免选中同名但无关的符号。"""
    folded = query.casefold()
    short_name = folded.rsplit(".", 1)[-1]

    def rank(item: dict) -> tuple:
        qualified = str(item.get("qualified_name") or "").casefold()
        name = str(item.get("name") or "").casefold()
        return (
            qualified == folded,
            qualified.endswith(f".{folded}"),
            name == short_name,
            qualified,
        )

    return sorted(symbols, key=rank, reverse=True)


def _reference_candidates(context: AgentContext, target: dict, *, limit: int = 20) -> list[dict]:
    """查找有源码支撑的引用候选；它们不是已解析调用边。"""
    name = str(target.get("name") or "").strip()
    if not name:
        return []
    rows = list_evidence_units(context.repo_id, context.snapshot_id, limit=1000, query=name)
    target_id = str(target.get("evidence_id") or "")
    selected = []
    for row in rows:
        path = str(row.get("file_path") or "").replace("\\", "/")
        content = str(row.get("content") or "")
        if row.get("id") == target_id or not re.search(rf"\b{re.escape(name)}\s*\(", content):
            continue
        if not (path.endswith(".py") and ("/app/" in f"/{path}" or path.startswith("tests/") or "/tests/" in f"/{path}")):
            continue
        selected.append({
            **row,
            "chunk_id": row["id"],
            "reason": "源码引用候选（未解析为调用边）",
            "score": 900.0 if "test" in path.casefold() else 950.0,
            "specialist_priority": 2,
            "signals": ["specialist", "lexical_reference"],
        })
        if len(selected) >= limit:
            break
    return selected


def dependency_impact(context: AgentContext) -> ToolResult:
    """从规范符号与持久化关系分析影响，并保留有界引用候选。"""
    query = _symbol_term(context.question)
    short_query = query.rsplit(".", 1)[-1]
    symbols = list_symbols(context.repo_id, context.snapshot_id, query=query, limit=50)
    if not symbols and short_query != query:
        symbols = list_symbols(context.repo_id, context.snapshot_id, query=short_query, limit=50)
    ranked = _rank_target_symbols(symbols, query)
    target = ranked[0] if ranked else None
    relations = list_relations(context.repo_id, context.snapshot_id, limit=10000)
    symbol_by_id = {
        item["id"]: item
        for item in list_symbols(context.repo_id, context.snapshot_id, limit=None)
    }

    evidence: list[dict] = []
    resolved_relations: list[dict] = []
    if target:
        hydrated = _hydrated_evidence(
            context, target.get("evidence_id"), "目标符号定义",
            score=1000.0, specialist_priority=3,
        )
        if hydrated:
            evidence.append(hydrated)
        for relation in relations:
            if relation.get("target_symbol_id") != target.get("id"):
                continue
            if relation.get("relation_type") != "calls" or not relation.get("observed"):
                continue
            if relation.get("resolver_status") not in {None, "resolved"}:
                continue
            source = symbol_by_id.get(relation.get("source_symbol_id"))
            if not source:
                continue
            hydrated = _hydrated_evidence(
                context,
                source.get("evidence_id") or relation.get("source_evidence_id") or relation.get("evidence_id"),
                "已解析调用方",
                score=975.0,
                specialist_priority=3,
            )
            if hydrated:
                evidence.append(hydrated)
                resolved_relations.append(relation)
        evidence.extend(_reference_candidates(context, target))

    unique_paths = []
    for item in evidence:
        path = str(item.get("file_path") or "")
        if path and path not in unique_paths:
            unique_paths.append(path)
    limitation = None
    if target and not resolved_relations:
        limitation = "解析器未生成完整实例方法调用边；入口与测试仅标记为源码引用候选，不视为已解析调用关系。"
    elif not target:
        limitation = f"未在当前 Snapshot 中解析到目标符号 {query}。"
    return ToolResult(
        "dependency_impact",
        f"目标 {target.get('qualified_name') if target else query}；找到 {len(resolved_relations)} 条已解析调用关系和 "
        f"{sum(item.get('reason', '').startswith('源码引用候选') for item in evidence)} 条引用候选。",
        evidence,
        {
            "query": query,
            "target": target,
            "resolved_relations": resolved_relations[:100],
            "evidence_paths": unique_paths,
        },
        limitation=limitation,
    )


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
        evidence.append({
            **row,
            "chunk_id": row["id"],
            "reason": "安全规则命中",
            "score": 1000.0,
            "specialist_priority": 3,
            "signals": ["specialist", "security_rule"],
        })
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
