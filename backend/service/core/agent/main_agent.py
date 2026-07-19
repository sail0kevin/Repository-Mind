"""RepoMind Main Agent：检索优先、条件工具、统一综合和规则降级。"""
from __future__ import annotations

import time

from service.core.agent.models import AgentContext, MainAgentResult
from service.core.agent.router import route_question
from service.core.agent.tools import run_tool
from service.core.evidence import EvidenceAssembler
from service.core.qa import answer_question
from service.core.repo_map import build_repo_map, build_repo_summary
from service.core.retrieval import HybridRetriever
from service.storage.agent_trace_store import finish_agent_trace, record_agent_step, start_agent_trace
from service.storage.chunk_store import count_chunks
from service.storage.evidence_store import get_evidence_unit, list_symbols
from service.storage.repository_store import get_repo_record, list_file_records


def _refs(items: list[dict]) -> list[dict]:
    refs = []
    for item in items:
        refs.append({
            "chunk_id": item.get("chunk_id") or item.get("id") or "",
            "file_path": item.get("file_path") or item.get("path") or "repository",
            "start_line": item.get("start_line"),
            "end_line": item.get("end_line"),
            "reason": item.get("reason") or "检索匹配",
        })
    return refs


def _merge_tool_evidence(existing: list[dict], additions: list[dict], *, specialist_limit: int = 3) -> list[dict]:
    """规范化并合并有正文的 Specialist 候选，最终预算由 Assembler 统一执行。"""
    merged = list(existing)
    seen = {
        (
            str(item.get("chunk_id") or item.get("id") or "").strip(),
            str(item.get("file_path") or item.get("path") or "").strip().replace("\\", "/"),
            item.get("start_line"),
            item.get("end_line"),
        ): index
        for index, item in enumerate(merged)
    }
    added = 0
    used_paths: set[str] = set()
    ordered = sorted(
        additions,
        key=lambda item: (
            -int(item.get("specialist_priority") or 0),
            -float(item.get("score") or 0.0),
            str(item.get("file_path") or item.get("path") or ""),
        ),
    )
    # Specialist 槽位先保证路径多样，再按优先级补齐。
    diverse = []
    remaining = []
    for item in ordered:
        path = str(item.get("file_path") or item.get("path") or "").strip().replace("\\", "/")
        if path and path not in used_paths:
            diverse.append(item)
            used_paths.add(path)
        else:
            remaining.append(item)
    for item in diverse + remaining:
        if added >= max(0, specialist_limit):
            break
        path = str(item.get("file_path") or item.get("path") or "").strip().replace("\\", "/")
        while "//" in path:
            path = path.replace("//", "/")
        content = str(item.get("content") or item.get("snippet") or "").strip()
        if not path or not content:
            continue
        candidate = dict(item)
        candidate["file_path"] = path
        candidate["content"] = str(item.get("content") or item.get("snippet") or "")
        candidate.setdefault("reason", "Specialist Tool evidence")
        candidate.setdefault("specialist_priority", 1)
        key = (
            str(candidate.get("chunk_id") or candidate.get("id") or "").strip(),
            path,
            candidate.get("start_line"),
            candidate.get("end_line"),
        )
        if key in seen:
            existing_index = seen[key]
            existing = merged[existing_index]
            if int(candidate.get("specialist_priority") or 0) > int(existing.get("specialist_priority") or 0):
                merged[existing_index] = {**existing, **candidate}
            continue
        seen[key] = len(merged)
        merged.append(candidate)
        added += 1
    return merged


def _direct_symbol_evidence(context: AgentContext) -> list[dict]:
    """为普通限定符号问题补入真实定义，不触发 Specialist Tool。"""
    from service.core.agent.tools import _symbol_term

    query = _symbol_term(context.question)
    if not ("." in query or "_" in query or any(char.isupper() for char in query[1:])):
        return []
    short_name = query.rsplit(".", 1)[-1]
    symbols = list_symbols(context.repo_id, context.snapshot_id, query=query, limit=20)
    if not symbols and short_name != query:
        symbols = list_symbols(context.repo_id, context.snapshot_id, query=short_name, limit=20)
    folded = query.casefold()
    symbols.sort(key=lambda item: (
        str(item.get("qualified_name") or "").casefold() == folded,
        str(item.get("qualified_name") or "").casefold().endswith(f".{folded}"),
        str(item.get("name") or "").casefold() == short_name.casefold(),
    ), reverse=True)
    for symbol in symbols:
        evidence_id = symbol.get("evidence_id")
        row = get_evidence_unit(context.repo_id, evidence_id, context.snapshot_id) if evidence_id else None
        if row and str(row.get("content") or "").strip():
            return [{
                **row,
                "chunk_id": row["id"],
                "reason": "限定符号定义",
                "score": 1000.0,
                "specialist_priority": 2,
                "signals": ["symbol_definition"],
            }]
    return []


def run_main_agent(context: AgentContext) -> MainAgentResult:
    """执行一次有硬上限的 Main Agent 问答。"""
    plan = route_question(context.question)
    trace_id = start_agent_trace(context.repo_id, context.snapshot_id, context.question,
                                 mode=plan.intent, planner_version=plan.planner_version)
    step_no = 1
    record_agent_step(trace_id, step_no, "route", input_summary={"question": context.question},
                      output_summary={"intent": plan.intent, "tools": [tool.name for tool in plan.tools]})
    step_no += 1

    retrieval = HybridRetriever().retrieve(
        context.repo_id, context.snapshot_id, context.question, context.limit
    )
    retrieval_bundle = EvidenceAssembler().assemble(
        retrieval.items, commit=context.commit, limit=context.limit
    )
    retrieval_rows = [item.to_dict() for item in retrieval_bundle.items]
    evidence_candidates = list(retrieval.items)
    if not plan.tools:
        evidence_candidates = _merge_tool_evidence(
            evidence_candidates,
            _direct_symbol_evidence(context),
            specialist_limit=1,
        )
    record_agent_step(trace_id, step_no, "retrieval", tool_name="hybrid_retriever",
                      output_summary={"mode": retrieval.run.mode, **retrieval_bundle.stats},
                      evidence_refs=_refs(retrieval_rows))
    step_no += 1

    tool_summaries: list[str] = []
    limitations: list[str] = []
    for decision in plan.tools[:2]:
        started = time.perf_counter()
        try:
            result = run_tool(decision, context)
            evidence_candidates = _merge_tool_evidence(
                evidence_candidates,
                result.evidence,
                specialist_limit=min(3, context.limit),
            )
            tool_summaries.append(f"{decision.name}: {result.summary}")
            if result.limitation:
                limitations.append(result.limitation)
            record_agent_step(
                trace_id, step_no, "tool", tool_name=decision.name,
                status="succeeded", input_summary={"purpose": decision.purpose},
                output_summary={"summary": result.summary, "metadata": result.metadata,
                                "limitation": result.limitation},
                evidence_refs=result.evidence,
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        except Exception as exc:
            limitations.append(f"{decision.name} 执行失败：{exc}")
            record_agent_step(trace_id, step_no, "tool", tool_name=decision.name,
                              status="failed", input_summary={"purpose": decision.purpose},
                              duration_ms=(time.perf_counter() - started) * 1000, error=str(exc))
        step_no += 1

    final_bundle = EvidenceAssembler().assemble(
        evidence_candidates, commit=context.commit, limit=context.limit
    )
    evidence_rows = [item.to_dict() for item in final_bundle.items]

    repo = get_repo_record(context.repo_id) or {"id": context.repo_id, "alias": context.repo_id}
    repo_map = build_repo_map(
        repo,
        list_file_records(context.repo_id, limit=5000, snapshot_id=context.snapshot_id),
        chunk_count=count_chunks(context.repo_id, context.snapshot_id),
    )
    repo_summary = build_repo_summary(repo_map)
    if tool_summaries:
        repo_summary = {**repo_summary, "summary": (repo_summary.get("summary") or "") + "\n专业工具：" + "；".join(tool_summaries)}
    answer = answer_question(context.question, evidence_rows, repo_summary)
    if limitations:
        answer["answer"] += "\n\n限制说明：" + "；".join(limitations)
    generation_mode = "llm" if answer.get("used_llm") else "rule_fallback"
    record_agent_step(trace_id, step_no, "synthesis", status="succeeded",
                      output_summary={"generation_mode": generation_mode, "limitations": limitations,
                                      "evidence_stats": final_bundle.stats},
                      token_count=answer.get("token_count", 0), evidence_refs=_refs(evidence_rows))
    finish_agent_trace(trace_id, status="succeeded" if generation_mode == "llm" else "fallback",
                       answer=answer["answer"], confidence=answer.get("confidence", "low"),
                       token_count=answer.get("token_count", 0))
    return MainAgentResult(
        answer=answer["answer"], evidence=evidence_rows, confidence=answer.get("confidence", "low"),
        used_context=len(evidence_rows), trace_id=trace_id, next_steps=answer.get("next_steps", []),
        token_count=answer.get("token_count", 0), generation_mode=generation_mode,
    )
