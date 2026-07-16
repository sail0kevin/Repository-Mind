"""Main Agent 的确定性 Router；首版不让 LLM 决定是否调用工具。"""
from __future__ import annotations

from service.core.agent.models import AgentPlan, ToolDecision

_SECURITY = ("安全", "认证", "密钥", "注入", "权限", "漏洞", "secret", "token", "password", "security")
_IMPACT = ("影响", "依赖", "调用链", "谁调用", "受影响", "改动", "回归", "impact", "dependency", "call chain")
_TEST = ("测试", "用例", "失败", "运行", "启动", "报错", "test", "pytest", "vitest", "build")
_OVERVIEW = ("概览", "架构", "从哪里开始", "怎么读", "主要模块", "入口", "overview", "architecture", "reading guide")
_LANGUAGE = ("继承", "接口", "符号", "类结构", "函数结构", "方法列表", "typescript", "python", "class hierarchy", "symbol")


def _contains(question: str, keywords: tuple[str, ...]) -> bool:
    normalized = question.casefold()
    return any(keyword.casefold() in normalized for keyword in keywords)


def route_question(question: str) -> AgentPlan:
    """按问题意图选择最多两个只读 Specialist Tool。"""
    tools: list[ToolDecision] = []
    intent = "direct_qa"
    if _contains(question, _SECURITY):
        intent = "security_review"
        tools.append(ToolDecision("security_review", "检查安全规则、认证和敏感信息线索"))
    elif _contains(question, _IMPACT):
        intent = "dependency_impact"
        tools.append(ToolDecision("dependency_impact", "分析符号关系和一跳影响范围"))
    elif _contains(question, _TEST):
        intent = "test_runtime"
        tools.append(ToolDecision("test_runtime", "定位测试、启动和构建相关证据"))
    elif _contains(question, _OVERVIEW):
        intent = "repository_navigation"
        tools.append(ToolDecision("repository_navigator", "读取 Catalog 概览和阅读顺序"))
    elif _contains(question, _LANGUAGE):
        intent = "language_structure"
        tools.append(ToolDecision("language_structure", "查询符号和结构关系"))
    return AgentPlan(intent=intent, tools=tuple(tools[:2]))
