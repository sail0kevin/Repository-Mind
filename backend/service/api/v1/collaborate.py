"""
这个文件负责多智能体协作辩论接口。
它在整个框架里扮演"多 Agent 协调 API"的角色：接收前端发来的话题和智能体配置，
调用 MultiAgentDebateService 让多个 Agent 各自分析，最后返回每个 Agent 的贡献和综合摘要。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from urllib.parse import parse_qsl, urlsplit

from service.core.debate import MultiAgentDebateService
from service.core.evidence import EvidenceAssembler
from service.core.retrieval import HybridRetriever
from service.storage.agent_trace_store import finish_agent_trace, record_agent_step, start_agent_trace
from service.storage.repository_store import get_repo_record
from service.storage.snapshot_store import get_active_snapshot, get_snapshot

router = APIRouter(tags=["collaborate"])


class AgentLLMOverride(BaseModel):
    """单个智能体本次运行使用的临时模型覆盖。"""

    model: str | None = Field(default=None, min_length=1, max_length=200)
    base_url: str | None = Field(default=None, max_length=2048)
    api_key: str | None = Field(default=None, max_length=4096)

    @field_validator("model", "base_url", "api_key", mode="before")
    @classmethod
    def normalize_blank_values(cls, value):
        """把空字符串转成 None，表示继承全局配置。"""
        if isinstance(value, str):
            return value.strip() or None
        return value

    @model_validator(mode="after")
    def validate_endpoint_key_pair(self):
        """实际是否跨接口由模型调用层结合全局地址判断。"""
        if self.base_url:
            parsed = urlsplit(self.base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("专属 Base URL 必须是有效的 HTTP(S) 地址。")
            if parsed.username is not None or parsed.password is not None:
                raise ValueError("专属 Base URL 不能包含用户名或密码。")
            sensitive = {"api_key", "apikey", "key", "token", "access_token", "password", "secret", "credential"}
            if parsed.fragment or any(name.lower() in sensitive for name, _ in parse_qsl(parsed.query, keep_blank_values=True)):
                raise ValueError("专属 Base URL 不能包含凭据查询参数或 fragment。")
        return self


class CollaborateAgentPayload(BaseModel):
    """单个智能体的配置。"""

    name: str = Field(default="Agent", min_length=1, max_length=100)
    role: str = Field(default="developer", min_length=1, max_length=100)
    llm_override: AgentLLMOverride | None = None


class CollaborateRequest(BaseModel):
    """多智能体辩论请求。"""

    repo_id: str = Field(min_length=1, max_length=200)
    topic: str = Field(min_length=1, max_length=4000)
    snapshot_id: str | None = Field(default=None, max_length=200)
    agents: list[CollaborateAgentPayload] | None = Field(default=None, max_length=12)


class AgentContributionResponse(BaseModel):
    """单个智能体的分析贡献。"""

    agent_name: str
    role: str
    content: str
    used_llm: bool
    error: str | None = None


class CollaborateResponse(BaseModel):
    """多智能体辩论响应。"""

    topic: str
    repo_id: str
    contributions: list[AgentContributionResponse]
    summary: str
    agents_used_llm: int
    total_tokens_used: int
    snapshot_id: str | None = None
    commit: str | None = None
    trace_id: str | None = None
    mode: str = "legacy_multi_role"


# 默认智能体阵容：当用户不指定时，使用这套多视角组合。
DEFAULT_AGENTS = [
    {"name": "代码审查员", "role": "developer"},
    {"name": "测试工程师", "role": "tester"},
    {"name": "产品经理", "role": "pm"},
    {"name": "架构师", "role": "architect"},
]


@router.post("/collaborate", response_model=CollaborateResponse, deprecated=True)
def run_collaboration(request: CollaborateRequest) -> CollaborateResponse:
    """启动一次多智能体协作辩论。

    前端传入仓库 id 和分析话题，后端自动拉取仓库的文件和 chunk 作为上下文，
    然后让多个不同角色的 Agent 各自分析，最后汇总返回。

    如果用户不指定 agents 列表，默认使用 4 个角色的固定阵容。

    参数：
        request.repo_id: 已注册的仓库 id。
        request.topic: 分析话题。
        request.agents: 可选的智能体列表，每个包含 name 和 role。

    返回：
        CollaborateResponse，包含每个 Agent 的分析贡献和综合摘要。
    """

    record = get_repo_record(request.repo_id)
    if record is None:
        raise HTTPException(status_code=404, detail="没有找到指定仓库。")

    snapshot = get_snapshot(request.snapshot_id) if request.snapshot_id else get_active_snapshot(request.repo_id)
    if snapshot is None or snapshot["repo_id"] != request.repo_id:
        raise HTTPException(status_code=404, detail="没有找到指定快照。")
    if snapshot["status"] != "succeeded":
        raise HTTPException(status_code=409, detail="只有 succeeded 快照可以用于协作分析。")

    retrieval = HybridRetriever().retrieve(request.repo_id, snapshot["id"], request.topic, 12)
    bundle = EvidenceAssembler().assemble(retrieval.items, commit=snapshot["commit_hash"], limit=12)
    context = {
        "snapshot_id": snapshot["id"],
        "commit": snapshot["commit_hash"],
        "files": sorted({item.path for item in bundle.items}),
        "chunks": [
            {
                "file_path": item.path,
                "title": item.title,
                "symbol_name": item.symbol_name,
                "content": item.content,
                "snippet": item.content[:300],
                "start_line": item.start_line,
                "end_line": item.end_line,
            }
            for item in bundle.items
        ],
    }

    agents = [a.model_dump() for a in request.agents] if request.agents else DEFAULT_AGENTS
    trace_id = start_agent_trace(request.repo_id, snapshot["id"], request.topic,
                                 entrypoint="collaborate", mode="legacy_multi_role")
    record_agent_step(trace_id, 1, "retrieval", tool_name="hybrid_retriever",
                      output_summary=bundle.stats,
                      evidence_refs=[{"chunk_id": item.chunk_id, "file_path": item.path,
                                     "start_line": item.start_line, "end_line": item.end_line}
                                    for item in bundle.items])
    service = MultiAgentDebateService()
    try:
        result = service.run_debate(topic=request.topic, context=context, agents=agents)
        record_agent_step(trace_id, 2, "tool", tool_name="legacy_multi_role", status="succeeded",
                          output_summary={"agents": len(result.contributions),
                                          "agents_used_llm": result.agents_used_llm},
                          token_count=result.total_tokens_used)
        finish_agent_trace(trace_id, status="succeeded" if result.agents_used_llm else "fallback",
                           answer=result.summary, confidence="medium" if result.agents_used_llm else "low",
                           token_count=result.total_tokens_used)
    except Exception as exc:
        record_agent_step(trace_id, 2, "tool", tool_name="legacy_multi_role", status="failed", error=str(exc))
        finish_agent_trace(trace_id, status="failed", answer="", confidence="low", error=str(exc))
        raise

    return CollaborateResponse(
        topic=result.topic,
        repo_id=request.repo_id,
        contributions=[
            AgentContributionResponse(
                agent_name=c.agent_name,
                role=c.role,
                content=c.content,
                used_llm=c.used_llm,
                error=c.error,
            )
            for c in result.contributions
        ],
        summary=result.summary,
        agents_used_llm=result.agents_used_llm,
        total_tokens_used=result.total_tokens_used,
        snapshot_id=snapshot["id"],
        commit=snapshot["commit_hash"],
        trace_id=trace_id,
    )
