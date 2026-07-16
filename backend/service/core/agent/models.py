"""Main Agent 的稳定领域模型。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentContext:
    """一次问答固定使用的仓库快照上下文。"""

    repo_id: str
    snapshot_id: str
    commit: str
    question: str
    limit: int


@dataclass(frozen=True)
class ToolDecision:
    """规则 Router 产生的工具调用决策。"""

    name: str
    purpose: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentPlan:
    """最多包含两个 Specialist Tool 的确定性计划。"""

    intent: str
    tools: tuple[ToolDecision, ...]
    planner_version: str = "rule-router-v1"


@dataclass
class ToolResult:
    """Specialist Tool 的结构化结果。"""

    tool_name: str
    summary: str
    evidence: list[dict] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    limitation: str | None = None


@dataclass
class MainAgentResult:
    """可直接投影到旧 QAResponse 的 Main Agent 输出。"""

    answer: str
    evidence: list[dict]
    confidence: str
    used_context: int
    trace_id: str
    next_steps: list[str]
    token_count: int
    generation_mode: str
