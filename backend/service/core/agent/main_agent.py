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
    bundle = EvidenceAssembler().assemble(retrieval.items, commit=context.commit, limit=context.limit)
    evidence_rows = [item.to_dict() for item in bundle.items]
    record_agent_step(trace_id, step_no, "retrieval", tool_name="hybrid_retriever",
                      output_summary={"mode": retrieval.run.mode, **bundle.stats},
                      evidence_refs=_refs(evidence_rows))
    step_no += 1

    tool_summaries: list[str] = []
    limitations: list[str] = []
    for decision in plan.tools[:2]:
        started = time.perf_counter()
        try:
            result = run_tool(decision, context)
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
    generation_mode = "llm" if answer.get("token_count", 0) else "rule_fallback"
    record_agent_step(trace_id, step_no, "synthesis", status="succeeded",
                      output_summary={"generation_mode": generation_mode, "limitations": limitations},
                      token_count=answer.get("token_count", 0), evidence_refs=_refs(evidence_rows))
    finish_agent_trace(trace_id, status="succeeded" if generation_mode == "llm" else "fallback",
                       answer=answer["answer"], confidence=answer.get("confidence", "low"),
                       token_count=answer.get("token_count", 0))
    return MainAgentResult(
        answer=answer["answer"], evidence=evidence_rows, confidence=answer.get("confidence", "low"),
        used_context=len(evidence_rows), trace_id=trace_id, next_steps=answer.get("next_steps", []),
        token_count=answer.get("token_count", 0), generation_mode=generation_mode,
    )
