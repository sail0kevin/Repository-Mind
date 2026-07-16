u"""
这个文件负责调用 OpenAI 兼容的大模型接口生成问答。
它在整个框架里扮演"模型调用层"的角色：把检索证据和用户问题拼成 prompt，送给配置的 LLM，再返回带证据绑定的自然语言回答。

调用示例：
    answer = generate_llm_answer(question="入口在哪", evidence=[...], repo_summary=None)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMRuntimeConfig:
    """单次模型调用实际使用的配置，只在内存中存在。"""

    api_key: str
    base_url: str
    model: str
    temperature: float
    max_tokens: int


@dataclass(frozen=True)
class LLMResult:
    """一次 LLM 调用结果。"""

    answer: str
    used_llm: bool
    error: str | None = None
    token_count: int = 0


def _has_openai_package() -> bool:
    """检查运行环境是否安装了 openai SDK。

    没有安装时返回 False，调用方应回退到规则型回答。
    """

    try:
        import openai  # noqa: F401
        return True
    except Exception:
        return False


def _build_messages(
    question: str,
    evidence: list[dict],
    repo_summary: dict | None,
    system_prompt: str | None = None,
) -> list[dict]:
    """把用户问题、仓库概览和检索证据拼成聊天消息列表。

    这里之所以用系统消息规定"角色和输出格式"，是因为模型需要明确知道：
    必须优先引用证据、不能编造不存在的函数名、要给出后续追问建议。
    """

    grounding_prompt = (
        "你必须基于提供的证据片段回答代码仓库问题。"
        "如果证据不足，必须明确说'根据当前证据无法确定'，而不是编造答案。"
        "回答请用中文，先给结论，再用 [序号] 引用证据来源，最后给 1-3 条后续追问建议。"
    )
    effective_system_prompt = (
        f"{system_prompt.strip()}\n\n{grounding_prompt}"
        if system_prompt and system_prompt.strip()
        else f"你是本地仓库知识助手 RepoMind。{grounding_prompt}"
    )

    user_bits = [f"问题：{question}"]

    if repo_summary and repo_summary.get("summary"):
        user_bits.append(f"仓库概览：{repo_summary['summary']}")

    if evidence:
        evidence_lines = []
        for index, item in enumerate(evidence, start=1):
            title = item.get("title") or item.get("symbol_name") or item.get("file_path") or ""
            fp = item.get("file_path", "")
            sl = item.get("start_line", "?")
            el = item.get("end_line", "?")
            location = f"{fp}:{sl}-{el}"
            snippet = (item.get("snippet") or "")[:300]
            evidence_lines.append(f"[{index}] {title} ({location})\n{snippet}")
        user_bits.append("检索证据：\n" + "\n\n".join(evidence_lines))
    else:
        user_bits.append("检索证据：无。请直接说明证据不足，并建议用户先建立索引或换关键词。")

    return [
        {"role": "system", "content": effective_system_prompt},
        {"role": "user", "content": "\n\n".join(user_bits)},
    ]


def _load_runtime_settings() -> dict:
    """读取当前运行时配置（API key、base url、模型名、温度、最大 token）。

    这里不直接 import Settings，是因为 llm_client 只关心调用模型需要的字段，
    而且这样调用方可以更灵活地传 None 来回退到默认配置。
    """

    try:
        from service.storage.secret_store import get_llm_api_key
        from service.storage.settings_store import get_setting

        return {
            "api_key": get_llm_api_key() or "",
            "base_url": get_setting("llm_base_url", "https://api.openai.com/v1") or "https://api.openai.com/v1",
            "model": get_setting("llm_model", "gpt-4o-mini") or "gpt-4o-mini",
            "temperature": get_setting("llm_temperature", 0.2) if get_setting("llm_temperature") is not None else 0.2,
            "max_tokens": get_setting("llm_max_tokens", 2048) or 2048,
        }
    except Exception as exc:
        logger.warning("读取运行时配置失败，使用默认配置：%s", exc)
        return {
            "api_key": "",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o-mini",
            "temperature": 0.2,
            "max_tokens": 2048,
        }


def resolve_runtime_config(override: Mapping[str, str] | None = None) -> LLMRuntimeConfig:
    """合并全局配置和单个 Agent 的临时覆盖配置。"""

    runtime = _load_runtime_settings()
    cleaned = {
        key: str(value).strip()
        for key, value in (override or {}).items()
        if key in {"api_key", "base_url", "model"} and value is not None and str(value).strip()
    }

    global_base_url = str(runtime["base_url"]).strip()
    override_base_url = cleaned.get("base_url")
    override_api_key = cleaned.get("api_key")
    if override_base_url:
        parsed = urlparse(override_base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("专属 Base URL 必须是有效的 HTTP(S) 地址，且不能包含账号信息。")
        if override_base_url.rstrip("/") != global_base_url.rstrip("/") and not override_api_key:
            raise ValueError("使用不同的专属 Base URL 时，必须同时填写该接口自己的 API Key。")

    return LLMRuntimeConfig(
        api_key=override_api_key or str(runtime["api_key"]),
        base_url=override_base_url or global_base_url,
        model=cleaned.get("model") or str(runtime["model"]),
        temperature=float(runtime["temperature"]),
        max_tokens=int(runtime["max_tokens"]),
    )


def generate_llm_answer(
    question: str,
    evidence: list[dict],
    repo_summary: dict | None = None,
    *,
    system_prompt: str | None = None,
    llm_override: Mapping[str, str] | None = None,
) -> LLMResult:
    """调用配置的 OpenAI 兼容 LLM 生成回答。

    参数：
        question: 用户提出的问题，必须非空。
        evidence: 从仓库检索到的证据片段列表，每个元素是包含 file_path/snippet 等字段的字典。
        repo_summary: 可选的仓库概览，由 build_repo_summary 生成。

    返回：
        LLMResult，包含回答文本、是否真正调用了模型、以及可能的错误信息。

    原理：
        优先使用 openai SDK；如果没装 SDK 或者没有配置 API key，就返回 used_llm=False，
        让上层 QA 模块继续用规则型回答兜底。这样同一份代码既能在有网络+有 key 时
        给出模型回答，也能在离线环境下给出可读性尚可的规则型回答。
    """

    if not _has_openai_package():
        logger.info("openai SDK 未安装，回退到规则型回答。")
        return LLMResult(answer="", used_llm=False, error="openai SDK 未安装")

    try:
        runtime = resolve_runtime_config(llm_override)
    except ValueError as exc:
        return LLMResult(answer="", used_llm=False, error=str(exc))
    if not runtime.api_key:
        logger.info("未配置 llm_api_key，回退到规则型回答。")
        return LLMResult(answer="", used_llm=False, error="未配置 llm_api_key")

    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=runtime.api_key,
            base_url=runtime.base_url,
            timeout=60,
        )
    except Exception:
        logger.exception("初始化 OpenAI 兼容客户端失败。")
        return LLMResult(answer="", used_llm=False, error="初始化模型客户端失败，请检查接口配置。")

    messages = _build_messages(question, evidence, repo_summary, system_prompt)

    try:
        response = client.chat.completions.create(
            model=runtime.model,
            messages=messages,
            temperature=runtime.temperature,
            max_tokens=runtime.max_tokens,
        )
        answer = response.choices[0].message.content if response.choices else ""
        # 从 API 响应中提取真实的 token 消耗量
        # 支持多种格式：OpenAI、LongCat、DeepSeek 等
        token_count = 0
        if hasattr(response, "usage") and response.usage:
            # 方式1直接读取 total_tokens 属性
            token_count = getattr(response.usage, "total_tokens", 0) or 0
            # 方式2如果 total_tokens 不存在，尝试相加 prompt_tokens + completion_tokens
            if not token_count:
                prompt_tokens = getattr(response.usage, "prompt_tokens", 0) or 0
                completion_tokens = getattr(response.usage, "completion_tokens", 0) or 0
                token_count = prompt_tokens + completion_tokens
            # 方式3如果 usage 是字典格式
            if not token_count and isinstance(response.usage, dict):
                token_count = response.usage.get("total_tokens", 0) or 0
                if not token_count:
                    token_count = (response.usage.get("prompt_tokens", 0) or 0) + (response.usage.get("completion_tokens", 0) or 0)
        if not answer:
            return LLMResult(answer="", used_llm=False, error="模型返回空内容", token_count=token_count)
        return LLMResult(answer=answer.strip(), used_llm=True, token_count=token_count)
    except Exception:
        logger.exception("调用 OpenAI 兼容模型失败。")
        return LLMResult(answer="", used_llm=False, error="模型调用失败，请检查网络、额度和模型配置。")
