"""
这个文件负责多智能体协作辩论接口。
它在整个框架里扮演"多 Agent 协调 API"的角色：接收前端发来的话题和智能体配置，
调用 MultiAgentDebateService 让多个 Agent 各自分析，最后返回每个 Agent 的贡献和综合摘要。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

from service.core.debate import MultiAgentDebateService
from service.storage.repository_store import get_repo_record, list_file_records
from service.storage.chunk_store import list_chunk_records

router = APIRouter(tags=["collaborate"])


class AgentLLMOverride(BaseModel):
    """单个智能体本次运行使用的临时模型覆盖。"""

    model: str | None = Field(default=None, max_length=200)
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
        if self.base_url and not self.base_url.startswith(("http://", "https://")):
            raise ValueError("专属 Base URL 必须是 HTTP(S) 地址。")
        return self


class CollaborateAgentPayload(BaseModel):
    """单个智能体的配置。"""

    name: str = Field(default="Agent", max_length=100)
    role: str = Field(default="developer", max_length=100)
    llm_override: AgentLLMOverride | None = None


class CollaborateRequest(BaseModel):
    """多智能体辩论请求。"""

    repo_id: str
    topic: str
    agents: list[CollaborateAgentPayload] | None = None


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


# 默认智能体阵容：当用户不指定时，使用这套多视角组合。
DEFAULT_AGENTS = [
    {"name": "代码审查员", "role": "developer"},
    {"name": "测试工程师", "role": "tester"},
    {"name": "产品经理", "role": "pm"},
    {"name": "架构师", "role": "architect"},
]


@router.post("/collaborate", response_model=CollaborateResponse)
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

    # 收集上下文：文件清单 + 已索引的 chunk。
    files = list_file_records(request.repo_id, limit=5000)
    chunks = list_chunk_records(request.repo_id, limit=200)

    context = {
        "files": [
            {
                "relative_path": f["relative_path"],
                "language": f["language"],
                "file_type": f["file_type"],
            }
            for f in files
        ],
        "chunks": [
            {
                "file_path": c.get("file_path", ""),
                "title": c.get("title"),
                "symbol_name": c.get("symbol_name"),
                "content": c.get("content", ""),
                "snippet": c.get("content", "")[:300],
            }
            for c in chunks
        ],
    }

    # 使用用户指定的 agents，或默认阵容。
    agents = [a.model_dump() for a in request.agents] if request.agents else DEFAULT_AGENTS

    service = MultiAgentDebateService()
    result = service.run_debate(topic=request.topic, context=context, agents=agents)

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
    )

