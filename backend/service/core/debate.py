"""
这个文件负责多智能体协作辩论服务。
它在整个框架里扮演"多 Agent 协调层"的角色：把一个复杂任务拆成多个子任务，
让不同的智能体（每个有自己的角色和视角）各自分析一部分内容，最后汇总成一份综合报告。

调用示例：
    service = MultiAgentDebateService()
    result = service.run_debate(
        topic="分析这个项目的架构",
        context={"files": [...], "chunks": [...]},
        agents=[
            {"name": "CodeReviewer", "role": "developer"},
            {"name": "DocsReviewer", "role": "pm"},
        ],
    )
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from service.core.llm_client import LLMResult, generate_llm_answer

logger = logging.getLogger(__name__)

# 每种角色对应的系统提示：告诉模型它应该从什么视角去分析。
ROLE_SYSTEM_PROMPTS: dict[str, str] = {
    "developer": (
        "你是一个资深代码审查者。请从代码质量、架构设计、可维护性和潜在 Bug 的角度分析问题。"
        "回答时请引用具体文件名和行号，用 [序号] 标注证据来源。"
    ),
    "tester": (
        "你是一个高级测试工程师。请从测试覆盖、边界条件、异常处理和安全漏洞的角度分析问题。"
        "回答时请引用具体文件名和行号，用 [序号] 标注证据来源。"
    ),
    "pm": (
        "你是一个产品经理。请从用户价值、功能完整性、文档质量和上手难度的角度分析问题。"
        "回答时请引用具体文件或章节，用 [序号] 标注证据来源。"
    ),
    "architect": (
        "你是一个系统架构师。请从模块划分、依赖关系、扩展性和技术选型的角度分析问题。"
        "回答时请引用具体文件或组件，用 [序号] 标注证据来源。"
    ),
    "security": (
        "你是一个安全工程师。请从数据安全、权限控制、注入风险和依赖漏洞的角度分析问题。"
        "回答时请引用具体文件或配置项，用 [序号] 标注证据来源。"
    ),
}


@dataclass
class AgentContribution:
    """单个智能体在一次辩论中的贡献。"""

    agent_name: str
    role: str
    content: str
    used_llm: bool
    error: str | None = None


@dataclass
class DebateResult:
    """多智能体辩论的最终结果。"""

    topic: str
    contributions: list[AgentContribution] = field(default_factory=list)
    summary: str = ""
    total_tokens_used: int = 0
    agents_used_llm: int = 0


def build_agent_evidence_prompt(topic: str, context: dict, role: str, agent_name: str) -> str:
    """把用户话题和上下文拼成单个智能体的 prompt。

    这里把证据材料格式化成文本片段，让模型能直接引用。
    如果证据太多（超过 3000 字），就截断，避免超过模型的上下文窗口。
    """

    lines = [f"分析话题：{topic}", ""]

    # 按文件类型分组，让不同角色的 Agent 各取所需。
    files = context.get("files", [])
    if files:
        lines.append("=== 项目文件清单 ===")
        for file_info in files[:30]:
            if isinstance(file_info, dict):
                path = file_info.get("relative_path", file_info.get("file_path", ""))
                lang = file_info.get("language", "")
                lines.append(f"- {path} ({lang})" if lang else f"- {path}")
        lines.append("")

    chunks = context.get("chunks", [])
    if chunks:
        lines.append("=== 关键代码片段 ===")
        for idx, chunk in enumerate(chunks[:10], start=1):
            if isinstance(chunk, dict):
                fp = chunk.get("file_path", "")
                title = chunk.get("title") or chunk.get("symbol_name") or ""
                snippet = (chunk.get("snippet") or chunk.get("content") or "")[:400]
                label = f"{title} " if title else ""
                lines.append(f"[{idx}] {label}({fp})")
                lines.append(snippet)
                lines.append("")

    if not files and not chunks:
        lines.append("（暂无上下文材料，请基于你的通用知识给出建议。）")

    evidence_text = "\n".join(lines)
    # 截断过长的证据，控制在 3000 字以内，避免超过模型上下文窗口。
    if len(evidence_text) > 3000:
        evidence_text = evidence_text[:3000] + "\n...（已截断）"

    return evidence_text


class MultiAgentDebateService:
    """多智能体辩论服务：协调多个 Agent 从不同视角分析同一个话题。"""

    def run_debate(
        self,
        topic: str,
        context: dict,
        agents: list[dict],
    ) -> DebateResult:
        """运行一次多智能体辩论。

        参数：
            topic: 分析话题，例如"这个项目的入口在哪里"。
            context: 上下文材料，包含 files 和 chunks 两个可选字段。
            agents: 智能体列表，每个元素包含 name 和 role 字段。

        返回：
            DebateResult，包含每个 Agent 的贡献和综合摘要。
        """

        result = DebateResult(topic=topic)

        for agent in agents:
            agent_name = agent.get("name", "Agent")
            role = agent.get("role", "developer")

            # 为当前 Agent 构建专属 prompt。
            evidence_prompt = build_agent_evidence_prompt(topic, context, role, agent_name)

            system_prompt = (
                f"你是 {agent_name}。"
                f"{ROLE_SYSTEM_PROMPTS.get(role, '请从你的专业角色出发，给出准确、可执行的仓库分析。')}"
                "请基于以下材料分析；材料不足时请明确说明证据不足。"
            )

            evidence = [{"file_path": "context", "snippet": evidence_prompt}]
            llm_override = agent.get("llm_override") or None

            # 默认继承全局模型；只有用户填写覆盖项时才为当前 Agent 临时改用其他配置。
            llm_result: LLMResult = generate_llm_answer(
                question=f"请从{role}视角分析：{topic}",
                evidence=evidence,
                system_prompt=system_prompt,
                llm_override=llm_override,
            )

            contribution = AgentContribution(
                agent_name=agent_name,
                role=role,
                content=llm_result.answer or f"（{agent_name} 未能生成分析：{llm_result.error or '未知错误'}）",
                used_llm=llm_result.used_llm,
                error=llm_result.error,
            )

            result.contributions.append(contribution)
            if llm_result.used_llm:
                result.agents_used_llm += 1
            result.total_tokens_used += llm_result.token_count

        # 生成综合摘要：把所有 Agent 的观点串起来。
        result.summary = self._build_summary(result)
        return result

    def _build_summary(self, result: DebateResult) -> str:
        """把多个 Agent 的贡献综合成一段摘要。

        如果没有任何 Agent 返回内容，就返回一个友好的提示。
        """

        if not result.contributions:
            return "没有智能体参与分析。"

        parts = []
        for contrib in result.contributions:
            parts.append(f"[{contrib.agent_name}（{contrib.role}）]\n{contrib.content}")

        return "\n\n".join(parts)
