"""
这个文件负责定义后端 API 和存储层共享的数据模型。
它在整个框架里扮演“数据契约”的角色，让接口返回、数据库字段和前端展示保持一致。
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator




class HealthResponse(BaseModel):
    """桌面端用于确认后端身份和契约版本的健康检查响应。"""

    status: Literal["ok"] = "ok"
    app_name: str
    app_version: str
    api_version: str
    schema_version: str
    supported_schema_version: str
    database_schema_version: str
    backend_contract_version: str
    instance_id: str
    session_id: str | None = None
    database_identity: str


class CodeGraphStatsResponse(BaseModel):
    """代码图谱节点、边和解析诊断的稳定统计契约。"""

    repo_id: str
    snapshot_id: str
    total_nodes: int
    total_edges: int
    functions: int
    classes: int
    files_analyzed: int
    diagnostics: dict | list


class CodeGraphNodeResponse(BaseModel):
    """代码图谱中可供搜索和展示的节点。"""

    id: str
    name: str
    node_type: str
    file_path: str
    start_line: int | None = None
    end_line: int | None = None
    signature: str | None = None
    importance: int = 0


class CodeGraphSearchRequest(BaseModel):
    """旧 POST 搜索接口的兼容请求体。"""

    query: str | None = None
    q: str | None = None
    limit: int = Field(default=20, ge=1, le=100)


class CodeGraphSearchResponse(BaseModel):
    """代码图谱搜索响应，保留旧客户端使用的结果别名和统计字段。"""

    repo_id: str
    snapshot_id: str
    query: str
    matches: list[CodeGraphNodeResponse]
    results: list[CodeGraphNodeResponse]
    functions: list[CodeGraphNodeResponse]
    stats: CodeGraphStatsResponse


class CodeGraphImportantResponse(BaseModel):
    """按连接度排序的重要代码节点响应，兼容旧函数列表字段。"""

    repo_id: str
    snapshot_id: str
    nodes: list[CodeGraphNodeResponse]
    results: list[CodeGraphNodeResponse]
    functions: list[CodeGraphNodeResponse]
    stats: CodeGraphStatsResponse


class CodeGraphEdgeResponse(BaseModel):
    """调用链中的一条有向关系。"""

    source_id: str
    target_id: str
    edge_type: str
    depth: int


class CodeGraphCallChainResponse(BaseModel):
    """指定符号的调用链响应，保留旧 chain 和 stats 字段。"""

    repo_id: str
    snapshot_id: str
    symbol: str
    direction: Literal["callers", "callees", "both"]
    depth: int
    root: CodeGraphNodeResponse | None
    nodes: list[CodeGraphNodeResponse]
    edges: list[CodeGraphEdgeResponse]
    chain: list[CodeGraphEdgeResponse]
    stats: CodeGraphStatsResponse


class CodeGraphClassResponse(BaseModel):
    """指定类节点及其直接图关系响应，保留旧 stats 字段。"""

    repo_id: str
    snapshot_id: str
    class_name: str
    class_node: CodeGraphNodeResponse | None
    related_nodes: list[CodeGraphNodeResponse]
    relations: list[CodeGraphEdgeResponse]
    stats: CodeGraphStatsResponse


class SettingsResponse(BaseModel):
    """应用配置响应；密钥只返回是否已配置和脱敏提示。"""

    api_base_url: str = 'http://127.0.0.1:8000/api/v1'
    llm_api_key_configured: bool = False
    llm_api_key_hint: str | None = None
    llm_base_url: str = 'https://api.openai.com/v1'
    llm_model: str = 'gpt-4o-mini'
    llm_temperature: float = 0.2
    llm_max_tokens: int = 2048
    embedding_provider: Literal['disabled', 'openai_compatible'] = 'disabled'
    embedding_api_key_configured: bool = False
    embedding_api_key_hint: str | None = None
    embedding_base_url: str = 'https://api.openai.com/v1'
    embedding_model: str = 'text-embedding-3-small'
    retrieval_limit: int = 8
    # 模型价格配置（每 1K token 的美元价格）
    input_cost_per_1k_tokens: float = 0.0005
    output_cost_per_1k_tokens: float = 0.0015


class SecretUpdate(BaseModel):
    """密钥更新动作：保持、设置新值或清除。"""

    action: Literal['unchanged', 'set', 'clear'] = 'unchanged'
    value: str | None = None

    @model_validator(mode='after')
    def validate_action_value(self) -> 'SecretUpdate':
        """只有 set 动作必须携带非空密钥，其他动作不能夹带值。"""

        if self.action == 'set' and not (self.value and self.value.strip()):
            raise ValueError('set 动作必须提供非空 value')
        if self.action != 'set' and self.value is not None:
            raise ValueError('只有 set 动作可以提供 value')
        return self


class SettingsUpdateRequest(BaseModel):
    """应用配置更新请求；llm_api_key 仅用于兼容旧客户端。"""

    api_base_url: str | None = Field(default=None, min_length=8, max_length=2048)
    llm_api_key_update: SecretUpdate | None = None
    llm_api_key: str | None = Field(default=None, max_length=4096, exclude=True)
    llm_base_url: str | None = Field(default=None, min_length=8, max_length=2048)
    llm_model: str | None = Field(default=None, min_length=1, max_length=200)
    llm_temperature: float | None = Field(default=None, ge=0, le=2)
    llm_max_tokens: int | None = Field(default=None, ge=64, le=131072)
    embedding_provider: Literal['disabled', 'openai_compatible'] | None = None
    embedding_api_key_update: SecretUpdate | None = None
    embedding_api_key: str | None = Field(default=None, max_length=4096, exclude=True)
    embedding_base_url: str | None = Field(default=None, min_length=8, max_length=2048)
    embedding_model: str | None = Field(default=None, min_length=1, max_length=200)
    retrieval_limit: int | None = Field(default=None, ge=1, le=50)
    input_cost_per_1k_tokens: float | None = Field(default=None, ge=0, le=1000)
    output_cost_per_1k_tokens: float | None = Field(default=None, ge=0, le=1000)

    @field_validator('api_base_url', 'llm_base_url', 'embedding_base_url')
    @classmethod
    def validate_provider_url(cls, value: str | None) -> str | None:
        """允许 localhost，但拒绝 URL 内嵌账号和疑似凭据参数。"""
        if value is None:
            return None
        from urllib.parse import parse_qsl, urlsplit
        parsed = urlsplit(value.strip())
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
            raise ValueError('Base URL 必须是有效的 HTTP(S) 地址。')
        if parsed.username is not None or parsed.password is not None:
            raise ValueError('Base URL 不能包含用户名或密码。')
        sensitive = {'api_key', 'apikey', 'key', 'token', 'access_token', 'password', 'secret', 'credential'}
        if parsed.fragment or any(name.lower() in sensitive for name, _ in parse_qsl(parsed.query, keep_blank_values=True)):
            raise ValueError('Base URL 不能包含凭据查询参数或 fragment。')
        return value.strip()

    def secret_update(self) -> SecretUpdate:
        """把新旧两种请求格式统一为明确的密钥动作。"""

        if self.llm_api_key_update is not None:
            return self.llm_api_key_update
        if self.llm_api_key is None:
            return SecretUpdate(action='unchanged')
        if self.llm_api_key.strip():
            return SecretUpdate(action='set', value=self.llm_api_key)
        return SecretUpdate(action='clear')

    def embedding_secret_update(self) -> SecretUpdate:
        """把新旧两种 Embedding 密钥格式统一为明确动作。"""

        if self.embedding_api_key_update is not None:
            return self.embedding_api_key_update
        if self.embedding_api_key is None:
            return SecretUpdate(action='unchanged')
        if self.embedding_api_key.strip():
            return SecretUpdate(action='set', value=self.embedding_api_key)
        return SecretUpdate(action='clear')

class ErrorBody(BaseModel):
    """统一错误响应的内部结构。"""

    code: str
    message: str
    detail: str | None = None
    trace_id: str


class ErrorResponse(BaseModel):
    """统一错误响应。"""

    error: ErrorBody


class RepoCreateRequest(BaseModel):
    """注册本地仓库的请求。"""

    repo_path: str = Field(min_length=1)
    remote_url: str | None = None
    branch: str | None = None
    alias: str | None = None


class SnapshotResponse(BaseModel):
    """仓库某次 Git 提交对应的只读快照信息。"""

    snapshot_id: str
    repo_id: str
    commit: str
    branch: str | None = None
    status: str
    error: str | None = None
    is_active: bool = False
    created_at: str
    updated_at: str
    finished_at: str | None = None


class SnapshotListResponse(BaseModel):
    """仓库快照列表及当前激活快照。"""

    repo_id: str
    active_snapshot_id: str | None = None
    snapshots: list[SnapshotResponse]


class SnapshotRefreshResponse(BaseModel):
    """刷新仓库并启动快照索引后的响应。"""

    repo_id: str
    snapshot_id: str
    commit: str
    status: str
    job_id: str | None = None


class RepoResponse(BaseModel):
    """仓库基础信息响应。"""

    repo_id: str
    alias: str
    repo_path: str
    remote_url: str | None
    branch: str | None
    current_commit: str | None
    status: str
    file_count: int = 0
    snapshot_id: str | None = None
    commit: str | None = None


class RepoCreateResponse(BaseModel):
    """仓库注册响应。"""

    repo_id: str
    status: str
    current_commit: str | None
    file_count: int
    job_id: str | None = None


class FileRecordResponse(BaseModel):
    """文件扫描记录响应。"""

    id: str
    repo_id: str
    snapshot_id: str
    relative_path: str
    language: str | None
    file_type: str
    extension: str | None
    size_bytes: int
    line_count: int | None
    is_binary: bool
    is_test_file: bool
    ignored_reason: str | None
    hash: str | None
    parse_status: str


class FileDetailResponse(FileRecordResponse):
    """文件详情响应，包含只读文本预览。"""

    content: str | None = None
    content_truncated: bool = False


class ChunkDetailResponse(BaseModel):
    """知识片段详情响应；旧 NULL 字段在 API 层归一化。"""

    id: str
    repo_id: str
    snapshot_id: str
    file_id: str
    file_path: str
    chunk_type: str
    title: str | None
    symbol_name: str | None
    start_line: int | None
    end_line: int | None
    content: str = ""
    content_hash: str = ""
    token_count: int | None
    embedding_status: str = "pending"
    source_type: str = "text"
    metadata_json: str | None
    parent_id: str | None


class ParserFactListResponse(BaseModel):
    """规范解析事实列表的统一外层，所有响应明确携带快照。"""

    repo_id: str
    snapshot_id: str
    items: list[dict]


class IngestResponse(BaseModel):
    """仓库解析和关键词索引响应。"""

    repo_id: str
    status: str
    indexed_file_count: int
    chunk_count: int
    job_id: str | None = None


class JobRecordResponse(BaseModel):
    """API response for a persisted local job record."""

    id: str
    repo_id: str | None
    job_type: str
    status: Literal["queued", "running", "succeeded", "failed", "cancelled", "interrupted"]
    progress: float = Field(ge=0.0, le=1.0)
    message: str | None
    error: str | None
    started_at: str | None
    finished_at: str | None
    created_at: str
    updated_at: str


class JobListResponse(BaseModel):
    """API response for recent local job records."""

    jobs: list[JobRecordResponse]


class SearchRequest(BaseModel):
    """仓库关键词检索请求；不传 snapshot_id 时沿用 active 快照。"""

    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=50)
    snapshot_id: str | None = None


class EvidenceItem(BaseModel):
    """检索结果证据项。"""

    file_path: str
    chunk_id: str
    start_line: int | None
    end_line: int | None
    source_type: str
    score: float
    reason: str
    snippet: str
    title: str | None = None
    symbol_name: str | None = None


class SearchResponse(BaseModel):
    """仓库关键词检索响应。"""

    repo_id: str
    query: str
    evidence: list[EvidenceItem]
    snapshot_id: str | None = None
    commit: str | None = None


class CatalogItemResponse(BaseModel):
    """单张 Repository Catalog 卡片及其生成溯源信息。"""

    id: str
    repo_id: str
    snapshot_id: str
    kind: str
    title: str
    path: str | None = None
    parent_id: str | None = None
    summary: str
    details: dict
    generation_method: str
    model: str | None = None
    prompt_version: str
    token_count: int = 0
    source_evidence_ids: list[str]
    freshness: str
    known_unknowns: list[str]
    created_at: str
    updated_at: str


class CatalogListResponse(BaseModel):
    """按快照列出的 Catalog 卡片。"""

    repo_id: str
    snapshot_id: str
    items: list[CatalogItemResponse]


class CatalogTreeNode(CatalogItemResponse):
    """Catalog 树节点。"""

    children: list["CatalogTreeNode"] = Field(default_factory=list)


class CatalogTreeResponse(BaseModel):
    """Repository Catalog 导航树。"""

    repo_id: str
    snapshot_id: str
    roots: list[CatalogTreeNode]


class QARequest(BaseModel):
    """仓库问答请求；不传 snapshot_id 时沿用 active 快照。"""

    question: str = Field(min_length=1)
    limit: int = Field(default=8, ge=1, le=20)
    snapshot_id: str | None = None


class QAResponse(BaseModel):
    """仓库问答响应。"""

    answer: str
    evidence: list[EvidenceItem]
    suggestions: list[str]
    confidence: str
    used_context: int
    trace_id: str
    next_steps: list[str]
    token_count: int = 0
    snapshot_id: str | None = None
    commit: str | None = None


class RepoMapResponse(BaseModel):
    """仓库地图响应。"""

    repo_id: str
    alias: str
    status: str
    branch: str | None
    current_commit: str | None
    file_count: int
    indexable_file_count: int
    chunk_count: int
    language_counts: dict[str, int]
    category_counts: dict[str, int]
    top_directories: dict[str, int]
    key_files: dict[str, list[str]]
    reading_order: list[str]
    snapshot_id: str | None = None
    commit: str | None = None


class RepoSummaryResponse(BaseModel):
    """仓库规则型摘要响应。"""

    repo_id: str
    alias: str
    summary: str
    languages: list[str]
    recommended_reading_order: list[str]
    next_steps: list[str]
    snapshot_id: str | None = None
    commit: str | None = None


class WorkflowAnalyzeRequest(BaseModel):
    """首次工作流分析请求；不传 snapshot_id 时沿用当前 active 快照。"""

    repo_id: str | None = None
    github_url: str | None = None
    alias: str | None = None
    auto_ingest: bool = True
    snapshot_id: str | None = None


class WorkflowEvidenceItem(BaseModel):
    """工作流报告中的证据项。"""

    file_path: str
    chunk_id: str = ""
    start_line: int | None = None
    end_line: int | None = None
    source_type: str
    score: float
    reason: str
    snippet: str = ""
    title: str | None = None
    symbol_name: str | None = None


class WorkflowFindingResponse(BaseModel):
    """工作流 Agent 的单条发现。"""

    title: str
    detail: str
    severity: str
    evidence: list[WorkflowEvidenceItem]


class WorkflowSectionResponse(BaseModel):
    """工作流报告的分工章节。"""

    key: str
    title: str
    findings: list[WorkflowFindingResponse]


class WorkflowRepoResponse(BaseModel):
    """工作流报告里的仓库摘要。"""

    repo_id: str
    alias: str
    repo_path: str
    remote_url: str | None
    branch: str | None
    current_commit: str | None


class WorkflowRegistrationResponse(BaseModel):
    """GitHub 仓库已登记但尚无 succeeded 快照时的明确响应。"""

    response_type: Literal["registration"] = "registration"
    repo_id: str
    status: Literal["registered"] = "registered"
    current_commit: str | None
    file_count: int
    job_id: str | None = None


class WorkflowReportResponse(BaseModel):
    """绑定 succeeded 快照的完整工作流分析报告响应。"""

    response_type: Literal["workflow_report"] = "workflow_report"
    analysis_id: str
    status: str
    repo: WorkflowRepoResponse
    summary: str
    sections: list[WorkflowSectionResponse]
    next_steps: list[str]
    limitations: list[str]
    markdown: str
    snapshot_id: str
    commit: str


class LegacyWorkflowReportResponse(BaseModel):
    """旧持久化报告读取契约；历史记录可能尚未保存快照字段。"""

    response_type: Literal["workflow_report"] = "workflow_report"
    analysis_id: str
    status: str
    repo: WorkflowRepoResponse
    summary: str
    sections: list[WorkflowSectionResponse]
    next_steps: list[str]
    limitations: list[str]
    markdown: str
    snapshot_id: str | None = None
    commit: str | None = None


class AnalysisReportSummaryResponse(BaseModel):
    """分析报告历史摘要。"""

    id: str
    repo_id: str
    analysis_type: str
    status: str
    summary: str
    created_at: str


class AnalysisReportListResponse(BaseModel):
    """分析报告历史列表响应。"""

    repo_id: str
    reports: list[AnalysisReportSummaryResponse]
