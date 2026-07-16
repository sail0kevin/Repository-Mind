"""Catalog 可选 LLM 增强；任何失败都返回原始规则卡片。"""
from __future__ import annotations

from service.core.catalog.models import CatalogItem
from service.core.llm_client import generate_llm_answer, resolve_runtime_config

PROMPT_VERSION = "catalog-summary-v1"


def enhance_catalog_items(items: list[CatalogItem]) -> list[CatalogItem]:
    """逐项增强摘要；无 Key、SDK 缺失、网络错误或空回答时保留规则版。"""
    enhanced: list[CatalogItem] = []
    for item in items:
        evidence = [{
            "file_path": item.path or "repository",
            "start_line": None,
            "end_line": None,
            "title": item.title,
            "snippet": item.summary,
        }]
        result = generate_llm_answer(
            question=f"请用一段简洁中文改写这张 {item.kind} Catalog 卡片，不增加规则事实之外的信息。",
            evidence=evidence,
            system_prompt="你是 Repository Catalog 摘要器。不得添加输入中不存在的事实、路径或符号。",
        )
        if not result.used_llm or not result.answer.strip():
            enhanced.append(item)
            continue
        try:
            model = resolve_runtime_config().model
        except Exception:
            model = "configured-model"
        enhanced.append(item.with_enhancement(result.answer.strip(), model, result.token_count, PROMPT_VERSION))
    return enhanced
