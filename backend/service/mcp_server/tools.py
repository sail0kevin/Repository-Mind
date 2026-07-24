"""
这个文件负责 MCP 的 5 个 Phase 1 工具实现。
每个工具只做参数校验、调用现成核心模块、把结果套进统一 envelope，不重新实现扫描/检索/关系分析逻辑。
"""
from __future__ import annotations

from service.core.agent.models import AgentContext
from service.core.agent.tools import _rank_target_symbols, dependency_impact, test_runtime
from service.core.evidence import EvidenceAssembler
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
from service.storage.evidence_store import list_evidence_units, list_relations, list_symbols
from service.storage.repository_store import list_file_records


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
    normalized_limit = clamp_limit(limit, default=10)

    try:
        retrieval = HybridRetriever().retrieve(
            repo_id, guard.snapshot["id"], normalized_query, normalized_limit
        )
        bundle = EvidenceAssembler().assemble(
            retrieval.items, commit=guard.snapshot["commit_hash"], limit=normalized_limit
        )
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
        symbols = list_symbols(repo_id, guard.snapshot["id"], query=normalized_query, limit=50)
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
        evidence.append(evidence_item(
            {
                "chunk_id": target.get("evidence_id"),
                "file_path": target.get("file_path"),
                "start_line": target.get("start_line"),
                "end_line": target.get("end_line"),
            },
            reason="符号定义",
        ))

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
        for item in ranked
    ]
    match_method = (
        "精确限定名匹配" if str(target.get("qualified_name") or "").casefold() == normalized_query.casefold()
        else "限定名后缀匹配" if str(target.get("qualified_name") or "").casefold().endswith(f".{normalized_query.casefold()}")
        else "短名称匹配"
    )
    limitations = []
    if len(ranked) > 1:
        limitations.append(f"找到 {len(ranked)} 个同名/相似符号，已按 {match_method} 排序，data.candidates 中给出全部候选。")

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
            "relations": [
                {
                    "relation_type": item.get("relation_type"),
                    "source_symbol_id": item.get("source_symbol_id"),
                    "target_symbol_id": item.get("target_symbol_id"),
                    "observed": bool(item.get("observed")),
                    "resolver_status": item.get("resolver_status"),
                }
                for item in related[:100]
            ],
            "candidates": candidates,
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
                for item in result.metadata.get("resolved_relations", [])
            ],
            "definition_evidence": definition_evidence,
            "resolved_caller_evidence": resolved_evidence,
            "reference_candidate_evidence": reference_evidence,
            "summary": result.summary,
        },
        evidence=definition_evidence + resolved_evidence + reference_evidence,
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
            status="ok", data={"files": base_result.metadata.get("files", [])},
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
            "all_test_files": base_result.metadata.get("files", []),
        },
        evidence=related_evidence or [
            evidence_item({"chunk_id": "", "file_path": item, "start_line": None, "end_line": None},
                          reason="测试/运行文件（未确认与目标符号相关）")
            for item in sorted(test_paths)
        ],
        limitations=limitations,
    )
