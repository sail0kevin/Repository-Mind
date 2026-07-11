"""
这个文件负责定义后端 API 和存储层共享的数据模型。
它在整个框架里扮演“数据契约”的角色，让接口返回、数据库字段和前端展示保持一致。
"""

from pydantic import BaseModel, Field




class SettingsResponse(BaseModel):
    """应用配置响应，包含所有可调整的运行时配置。"""

    api_base_url: str = 'http://127.0.0.1:8000/api/v1'
    llm_api_key: str = ''
    llm_base_url: str = 'https://api.openai.com/v1'
    llm_model: str = 'gpt-4o-mini'
    llm_temperature: float = 0.2
    llm_max_tokens: int = 2048
    embedding_model: str = 'text-embedding-3-small'
    retrieval_limit: int = 8
    # 模型价格配置（每 1K token 的美元价格）
    input_cost_per_1k_tokens: float = 0.0005
    output_cost_per_1k_tokens: float = 0.0015


class SettingsUpdateRequest(BaseModel):
    """应用配置更新请求，所有字段都是可选的。"""

    api_base_url: str | None = None
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_temperature: float | None = None
    llm_max_tokens: int | None = None
    embedding_model: str | None = None
    retrieval_limit: int | None = None
    input_cost_per_1k_tokens: float | None = None
    output_cost_per_1k_tokens: float | None = None
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
    """知识片段详情响应。"""

    id: str
    repo_id: str
    file_id: str
    file_path: str
    chunk_type: str
    title: str | None
    symbol_name: str | None
    start_line: int | None
    end_line: int | None
    content: str
    content_hash: str
    token_count: int | None
    embedding_status: str
    source_type: str
    metadata_json: str | None
    parent_id: str | None


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
    status: str
    progress: float
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
    """仓库关键词检索请求。"""

    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=50)


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


class QARequest(BaseModel):
    """仓库问答请求。"""

    question: str = Field(min_length=1)
    limit: int = Field(default=8, ge=1, le=20)


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


class RepoSummaryResponse(BaseModel):
    """仓库规则型摘要响应。"""

    repo_id: str
    alias: str
    summary: str
    languages: list[str]
    recommended_reading_order: list[str]
    next_steps: list[str]


class WorkflowAnalyzeRequest(BaseModel):
    """首次工作流分析请求。"""

    repo_id: str | None = None
    github_url: str | None = None
    alias: str | None = None
    auto_ingest: bool = True


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


class WorkflowReportResponse(BaseModel):
    """首次工作流分析报告响应。"""

    analysis_id: str
    status: str
    repo: WorkflowRepoResponse
    summary: str
    sections: list[WorkflowSectionResponse]
    next_steps: list[str]
    limitations: list[str]
    markdown: str


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
