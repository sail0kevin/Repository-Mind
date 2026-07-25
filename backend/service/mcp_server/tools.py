"""
这个文件负责 MCP 的只读工具实现。
每个工具只做参数校验、调用现成核心模块、把结果套进统一 envelope，不重新实现扫描/检索/关系分析逻辑。
"""
from __future__ import annotations

from service.core.agent.models import AgentContext
from service.core.agent.tools import _rank_target_symbols, dependency_impact, test_runtime
from service.core.evidence import EvidenceAssembler, EvidenceBudget
from service.core.repo_map import build_repo_map, build_repo_summary
from service.core.retrieval import HybridRetriever
from service.mcp_server.envelope import (
    clamp_limit,
    clamp_text,
    envelope,
    error_envelope,
    evidence_item,
)
from service.mcp_server.snapshot_guard import SnapshotGuardError, resolve_repo_and_snapshot
from service.storage.chunk_store import count_chunks
from service.storage.evidence_store import get_evidence_unit, list_evidence_units, list_relations, list_symbols
from service.storage.repository_store import list_file_records, list_repo_records


def list_repositories(limit: int | None = None) -> dict:
    """列出可供 MCP 查询的仓库和活动快照，不暴露本机绝对路径。"""
    normalized_limit = clamp_limit(limit, default=100, maximum=100)
    try:
        records = list_repo_records(limit=normalized_limit)
    except Exception as exc:  # noqa: BLE001 - MCP 进程不能因单次调用异常崩溃
        return error_envelope("", f"列出仓库失败：{exc}")

    repositories = [
        {
            "repo_id": item["id"],
            "alias": item.get("alias"),
            "branch": item.get("branch"),
            "snapshot_id": item.get("active_snapshot_id"),
            "commit": item.get("active_commit_hash"),
            "snapshot_status": item.get("active_snapshot_status"),
            "file_count": item.get("file_count") or 0,
            "indexed": item.get("active_snapshot_status") == "succeeded",
        }
        for item in records
    ]
    indexed_count = sum(1 for item in repositories if item["indexed"])
    limitations = []
    if indexed_count < len(repositories):
        limitations.append("未完成索引的仓库仅用于状态提示；其他查询工具只能使用带 succeeded 活动快照的仓库。")
    return envelope(
        repo_id="",
        status="ok",
        data={
            "repositories": repositories,
            "total": len(repositories),
            "indexed_count": indexed_count,
        },
        limitations=limitations,
    )


def _guard_or_envelope(repo_id: str, snapshot_id: str | None):
    """公共前置校验；返回 (guard_result, None) 或 (None, 已构造好的错误 envelope)。"""
    guard = resolve_repo_and_snapshot(repo_id, snapshot_id)
    if isinstance(guard, SnapshotGuardError):
        return None, envelope(repo_id=repo_id, snapshot_id=snapshot_id, status=guard.status, limitations=[guard.message])
    return guard, None


def repo_overview(repo_id: str, snapshot_id: str | None = None) -> dict:
    """返回仓库别名、commit、快照 ID、文件统计和推荐阅读顺序，明确标注只读索引结果。"""
    guard, failure = _guard_or_envelope(repo_id, snapshot_id)
    if failure is not None:
        return failure
    try:
        files = list_file_records(repo_id, limit=5000, snapshot_id=guard.snapshot["id"])
        repo_map = build_repo_map(guard.repo, files, chunk_count=count_chunks(repo_id, guard.snapshot["id"]))
        summary = build_repo_summary(repo_map)
    except Exception as exc:  # noqa: BLE001 - MCP 进程不能因单次调用异常崩溃
        return error_envelope(repo_id, f"生成仓库概览失败：{exc}", snapshot_id=guard.snapshot["id"])

    return envelope(
        repo_id=repo_id,
        snapshot_id=guard.snapshot["id"],
        commit=guard.snapshot["commit_hash"],
        status="ok",
        data={
            "alias": repo_map["alias"],
            "status": repo_map["status"],
            "branch": repo_map["branch"],
            "file_count": repo_map["file_count"],
            "indexable_file_count": repo_map["indexable_file_count"],
            "chunk_count": repo_map["chunk_count"],
            "language_counts": repo_map["language_counts"],
            "category_counts": repo_map["category_counts"],
            "key_files": repo_map["key_files"],
            "recommended_reading_order": summary["recommended_reading_order"],
            "summary": summary["summary"],
            "next_steps": summary["next_steps"],
        },
        limitations=["这是只读索引结果，不代表当前工作区未提交的改动。"],
    )


def search_code(repo_id: str, query: str, snapshot_id: str | None = None, limit: int | None = None) -> dict:
    """混合检索代码证据；embedding 不可用时如实报告 lexical 降级，不返回整份文件。"""
    guard, failure = _guard_or_envelope(repo_id, snapshot_id)
    if failure is not None:
        return failure
    normalized_query = clamp_text(query)
    if not normalized_query:
        return error_envelope(repo_id, "query 不能为空。", status="error", snapshot_id=guard.snapshot["id"])
    normalized_limit = clamp_limit(limit, default=6, maximum=20)

    try:
        retrieval = HybridRetriever().retrieve(
            repo_id, guard.snapshot["id"], normalized_query, normalized_limit
        )
        bundle = EvidenceAssembler(EvidenceBudget(
            total_tokens=1200,
            max_file_ratio=0.5,
            max_evidence_tokens=320,
            min_sources=2,
            max_items=6,
        )).assemble(retrieval.items, commit=guard.snapshot["commit_hash"], limit=normalized_limit)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(repo_id, f"检索失败：{exc}", snapshot_id=guard.snapshot["id"])

    mode = retrieval.run.mode
    semantic_channel = retrieval.run.channels.get("semantic")
    degraded = mode != "hybrid" or semantic_channel == 0
    status = "degraded" if degraded else "ok"
    limitations = []
    if mode != "hybrid":
        limitations.append("语义向量检索当前不可用（未配置或该快照没有 embedding），本次结果只使用关键词（lexical）检索，可能遗漏语义相关但字面不匹配的代码。")
    elif semantic_channel == 0:
        limitations.append("本次语义检索没有返回任何结果（embedding provider 可能异常或返回了空向量），已回退为只展示关键词（lexical）检索命中的结果。")

    evidence = [
        evidence_item(
            {
                "chunk_id": item.chunk_id,
                "file_path": item.path,
                "start_line": item.start_line,
                "end_line": item.end_line,
                "content": item.content,
            },
            reason=item.reason,
        )
        for item in bundle.items
    ]
    return envelope(
        repo_id=repo_id,
        snapshot_id=guard.snapshot["id"],
        commit=guard.snapshot["commit_hash"],
        status=status,
        data={
            "query": normalized_query,
            "retrieval_mode": mode,
            "evidence_budget": bundle.stats,
        },
        evidence=evidence,
        limitations=limitations,
    )


def get_symbol(repo_id: str, symbol_query: str, snapshot_id: str | None = None) -> dict:
    """按名称/限定名查询符号；同名符号存在时返回候选列表并说明匹配方式。"""
    guard, failure = _guard_or_envelope(repo_id, snapshot_id)
    if failure is not None:
        return failure
    normalized_query = clamp_text(symbol_query)
    if not normalized_query:
        return error_envelope(repo_id, "symbol_query 不能为空。", snapshot_id=guard.snapshot["id"])

    try:
        symbols = list_symbols(repo_id, guard.snapshot["id"], query=normalized_query, limit=20)
        ranked = _rank_target_symbols(symbols, normalized_query)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(repo_id, f"符号查询失败：{exc}", snapshot_id=guard.snapshot["id"])

    if not ranked:
        return envelope(
            repo_id=repo_id, snapshot_id=guard.snapshot["id"], commit=guard.snapshot["commit_hash"],
            status="not_found", data={"query": normalized_query},
            limitations=[f"未在当前 Snapshot 中找到匹配符号 {normalized_query}。"],
        )

    target = ranked[0]
    try:
        relations = list_relations(repo_id, guard.snapshot["id"], limit=10000)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(repo_id, f"关系查询失败：{exc}", snapshot_id=guard.snapshot["id"])
    related = [
        item for item in relations
        if item.get("source_symbol_id") == target.get("id") or item.get("target_symbol_id") == target.get("id")
    ]

    evidence = []
    if target.get("evidence_id"):
        definition = get_evidence_unit(repo_id, target["evidence_id"], guard.snapshot["id"])
        evidence.append(evidence_item(
            definition or {
                "chunk_id": target.get("evidence_id"),
                "file_path": target.get("file_path"),
                "start_line": target.get("start_line"),
                "end_line": target.get("end_line"),
            },
            reason="符号定义",
        ))

    symbol_by_id = {
        item.get("id"): item
        for item in list_symbols(repo_id, guard.snapshot["id"], limit=None)
    }

    def compact_symbol(symbol_id: str | None) -> dict:
        symbol = symbol_by_id.get(symbol_id)
        if not symbol:
            return {"symbol_id": symbol_id}
        return {
            "name": symbol.get("name"),
            "qualified_name": symbol.get("qualified_name"),
            "file_path": symbol.get("file_path"),
            "start_line": symbol.get("start_line"),
        }

    candidates = [
        {
            "symbol_id": item.get("id"),
            "name": item.get("name"),
            "qualified_name": item.get("qualified_name"),
            "symbol_kind": item.get("symbol_kind"),
            "file_path": item.get("file_path"),
            "start_line": item.get("start_line"),
            "end_line": item.get("end_line"),
        }
        for item in ranked[:5]
    ]
    static_call_candidates = []
    for relation in related:
        if relation.get("relation_type") != "calls" or relation.get("source_symbol_id") != target.get("id"):
            continue
        if relation.get("resolver_status") != "resolved" or not relation.get("target_symbol_id"):
            continue
        called_symbol = symbol_by_id.get(relation["target_symbol_id"])
        if not called_symbol:
            continue
        static_call_candidates.append({
            **compact_symbol(relation["target_symbol_id"]),
            "relation_type": "calls",
            "resolution": "static",
        })
        called_evidence = get_evidence_unit(
            repo_id, called_symbol.get("evidence_id") or "", guard.snapshot["id"]
        )
        if called_evidence:
            evidence.append(evidence_item(called_evidence, reason="静态解析到的调用目标"))
    match_method = (
        "精确限定名匹配" if str(target.get("qualified_name") or "").casefold() == normalized_query.casefold()
        else "限定名后缀匹配" if str(target.get("qualified_name") or "").casefold().endswith(f".{normalized_query.casefold()}")
        else "短名称匹配"
    )
    limitations = []
    if len(ranked) > 1:
        limitations.append(f"找到 {len(ranked)} 个同名/相似符号，已按 {match_method} 排序，仅返回前 5 个候选；如需进一步区分，请提供限定名或路径。")

    return envelope(
        repo_id=repo_id,
        snapshot_id=guard.snapshot["id"],
        commit=guard.snapshot["commit_hash"],
        status="ok",
        data={
            "query": normalized_query,
            "match_method": match_method,
            "symbol": {
                "name": target.get("name"),
                "qualified_name": target.get("qualified_name"),
                "symbol_kind": target.get("symbol_kind"),
                "file_path": target.get("file_path"),
                "start_line": target.get("start_line"),
                "end_line": target.get("end_line"),
            },
            "relation_count": len(related),
            "relations": [
                {
                    "type": item.get("relation_type"),
                    "source": compact_symbol(item.get("source_symbol_id")),
                    "target": compact_symbol(item.get("target_symbol_id")),
                    "observed": bool(item.get("observed")),
                    "resolver_status": item.get("resolver_status"),
                }
                for item in related[:10]
            ],
            "static_call_candidates": static_call_candidates,
            "candidates": candidates,
            "candidate_count": len(ranked),
        },
        evidence=evidence,
        limitations=limitations,
    )


def analyze_impact(repo_id: str, symbol_query: str, snapshot_id: str | None = None) -> dict:
    """静态影响分析；明确区分已解析调用关系与仅有源码支撑的引用候选。"""
    guard, failure = _guard_or_envelope(repo_id, snapshot_id)
    if failure is not None:
        return failure
    normalized_query = clamp_text(symbol_query)
    if not normalized_query:
        return error_envelope(repo_id, "symbol_query 不能为空。", snapshot_id=guard.snapshot["id"])

    try:
        context = AgentContext(
            repo_id=repo_id,
            snapshot_id=guard.snapshot["id"],
            commit=guard.snapshot["commit_hash"],
            question=normalized_query,
            limit=30,
        )
        result = dependency_impact(context)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(repo_id, f"影响分析失败：{exc}", snapshot_id=guard.snapshot["id"])

    resolved_evidence = []
    reference_evidence = []
    definition_evidence = []
    for item in result.evidence:
        reason = str(item.get("reason") or "")
        packaged = evidence_item(
            {
                "chunk_id": item.get("chunk_id") or item.get("id"),
                "file_path": item.get("file_path"),
                "start_line": item.get("start_line"),
                "end_line": item.get("end_line"),
                "content": item.get("content"),
            },
            reason=reason,
        )
        if reason == "目标符号定义":
            definition_evidence.append(packaged)
        elif reason.startswith("源码引用候选"):
            reference_evidence.append(packaged)
        else:
            resolved_evidence.append(packaged)

    target = result.metadata.get("target")
    status = "ok" if target else "not_found"
    limitations = [result.limitation] if result.limitation else []
    limitations.append("静态分析无法覆盖动态调用、反射或无法确定类型的实例调用；引用候选仅表示源码中出现了同名调用，未必是真实调用边。")
    all_impact_evidence = definition_evidence + resolved_evidence + reference_evidence
    evidence_groups = {
        "definition": [item["evidence_id"] for item in definition_evidence],
        "resolved_callers": [item["evidence_id"] for item in resolved_evidence],
        "reference_candidates": [item["evidence_id"] for item in reference_evidence],
    }

    return envelope(
        repo_id=repo_id,
        snapshot_id=guard.snapshot["id"],
        commit=guard.snapshot["commit_hash"],
        status=status,
        data={
            "query": result.metadata.get("query"),
            "target_symbol": {
                "name": target.get("name"),
                "qualified_name": target.get("qualified_name"),
                "file_path": target.get("file_path"),
                "start_line": target.get("start_line"),
                "end_line": target.get("end_line"),
            } if target else None,
            "resolved_relations": [
                {
                    "relation_type": item.get("relation_type"),
                    "source_symbol_id": item.get("source_symbol_id"),
                    "target_symbol_id": item.get("target_symbol_id"),
                }
                for item in result.metadata.get("resolved_relations", [])[:10]
            ],
            "evidence_groups": evidence_groups,
            "evidence_count": len(all_impact_evidence),
            "summary": result.summary,
        },
        evidence=all_impact_evidence,
        limitations=limitations,
    )


def find_related_tests(repo_id: str, symbol_query: str | None = None, snapshot_id: str | None = None) -> dict:
    """定位测试/构建/入口文件候选；只做定位，绝不执行目标仓库代码。"""
    guard, failure = _guard_or_envelope(repo_id, snapshot_id)
    if failure is not None:
        return failure
    normalized_query = clamp_text(symbol_query) if symbol_query else ""

    try:
        context = AgentContext(
            repo_id=repo_id,
            snapshot_id=guard.snapshot["id"],
            commit=guard.snapshot["commit_hash"],
            question=normalized_query or "test",
            limit=30,
        )
        base_result = test_runtime(context)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(repo_id, f"测试定位失败：{exc}", snapshot_id=guard.snapshot["id"])

    limitations = ["本工具只定位测试/构建/入口文件，不会执行目标仓库的任何代码或测试。"]
    if not normalized_query:
        limitations.append("未提供 symbol_query，本次返回的是全部测试/构建/入口文件候选，没有做针对性筛选。")
        evidence = [
            evidence_item({"chunk_id": "", "file_path": item, "start_line": None, "end_line": None},
                          reason="测试/运行文件")
            for item in [file.get("relative_path") for file in base_result.metadata.get("files", [])]
        ]
        return envelope(
            repo_id=repo_id, snapshot_id=guard.snapshot["id"], commit=guard.snapshot["commit_hash"],
            status="ok", data={"files": [file.get("relative_path") for file in base_result.metadata.get("files", [])]},
            evidence=evidence, limitations=limitations,
        )

    try:
        impact_context = AgentContext(
            repo_id=repo_id, snapshot_id=guard.snapshot["id"], commit=guard.snapshot["commit_hash"],
            question=normalized_query, limit=30,
        )
        impact_result = dependency_impact(impact_context)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(repo_id, f"关联测试定位失败：{exc}", snapshot_id=guard.snapshot["id"])

    test_paths = {file.get("relative_path") for file in base_result.metadata.get("files", [])}
    related_evidence = []
    for item in impact_result.evidence:
        path = str(item.get("file_path") or "").replace("\\", "/")
        if path not in test_paths and not any(token in path.casefold() for token in ("test", "spec")):
            continue
        related_evidence.append(evidence_item(
            {
                "chunk_id": item.get("chunk_id") or item.get("id"),
                "file_path": item.get("file_path"),
                "start_line": item.get("start_line"),
                "end_line": item.get("end_line"),
                "content": item.get("content"),
            },
            reason=str(item.get("reason") or ""),
        ))

    if not related_evidence:
        limitations.append(f"没有找到与 {normalized_query} 直接关联的测试文件引用证据，以下仍给出全部测试文件候选供人工核实。")

    return envelope(
        repo_id=repo_id, snapshot_id=guard.snapshot["id"], commit=guard.snapshot["commit_hash"],
        status="ok",
        data={
            "symbol_query": normalized_query,
            "matched_test_files": sorted({item["file_path"] for item in related_evidence}),
            "all_test_files": sorted(test_paths),
        },
        evidence=related_evidence or [
            evidence_item({"chunk_id": "", "file_path": item, "start_line": None, "end_line": None},
                          reason="测试/运行文件（未确认与目标符号相关）")
            for item in sorted(test_paths)
        ],
        limitations=limitations,
    )
