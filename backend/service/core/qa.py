"""
这个文件负责基于证据的规则型问答与混合问答编排。
它在整个框架里扮演"问答主流程"的角色：先尝试调用 LLM，没有模型或没有 key 时就回退到本地证据的中文规则回答。
"""
from __future__ import annotations

import uuid
from typing import Any

from service.core.llm_client import generate_llm_answer


def _fallback_answer(question: str, evidence: list[dict], repo_summary: dict | None) -> dict:
    """当没有模型可用时，基于本地证据生成规则型回答。"""
    summary_text = (repo_summary or {}).get("summary", "") if repo_summary else ""
    evidence_lines = []
    for index, item in enumerate(evidence[:5], start=1):
        path = str(item.get("file_path") or item.get("path") or "repository")
        start_line = item.get("start_line")
        end_line = item.get("end_line")
        if start_line is not None:
            end_line = end_line if end_line is not None else start_line
            location = f"{path}:{start_line}-{end_line}"
        else:
            location = path
        evidence_lines.append(f"[{index}] {location}: {(item.get('snippet') or item.get('content') or '')[:180]}")
    answer_parts = []
    if summary_text:
        answer_parts.append(f"根据当前仓库概览：{summary_text}")
    if evidence_lines:
        answer_parts.append("可以重点参考以下证据片段：\n" + "\n".join(evidence_lines))
    else:
        answer_parts.append("当前还没有可用于回答的检索证据。建议先完成仓库索引，或换一个更具体的关键词。")
    answer_parts.append("根据当前证据无法确定完整答案时，可能还需要结合源代码进一步确认。")
    return {
        "answer": "\n\n".join(answer_parts),
        "confidence": "low",
        "used_context": len(evidence),
        "trace_id": f"trace_{uuid.uuid4().hex}",
        "next_steps": [
            "尝试重新索引仓库",
            "更换更具体的问题关键词",
            "查看建议阅读的文件片段",
        ],
        "token_count": 0,
    }


def answer_question(
    question: str,
    evidence: list[dict],
    repo_summary: dict | None = None,
    *,
    system_prompt: str | None = None,
    llm_override: dict | None = None,
) -> Any:
    """生成问答结果。优先使用 LLM；失败时回退到规则型回答。"""
    llm_result = generate_llm_answer(
        question=question,
        evidence=evidence,
        repo_summary=repo_summary,
        system_prompt=system_prompt,
        llm_override=llm_override,
    )
    if llm_result.used_llm and llm_result.answer:
        return {
            "answer": llm_result.answer,
            "confidence": "high",
            "used_context": len(evidence),
            "trace_id": f"trace_{uuid.uuid4().hex}",
            "next_steps": [],
            "token_count": llm_result.token_count,
        }
    return _fallback_answer(question, evidence, repo_summary)
