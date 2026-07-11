"""
这个文件负责仓库注册和基本信息查询接口。
它在整个框架里扮演"仓库接入API"的角色，让桌面端可以把本地 Git 仓库登记到系统中。
"""

from pathlib import Path
import re
import sqlite3

from fastapi import APIRouter, HTTPException

from service.core.repo_scanner import (
    RepositoryScanError,
    get_current_branch,
    get_current_commit,
    resolve_repository_path,
    scan_repository_files,
    validate_git_repository,
)
from service.core.chunker import parse_text_file
from service.core.qa import answer_question
from service.core.repo_map import build_repo_map, build_repo_summary
from service.core.vector_store import replace_repo_vector_index, search_vectors
from service.core.workflow_analysis import build_workflow_report, clone_public_github_repo, register_cloned_repository
from service.storage.chunk_store import count_chunks, get_chunk_record, list_indexable_file_records, replace_repo_chunks, search_chunks
from service.core.codegraph.builder import CodeGraphBuilder
from service.core.codegraph.store import CodeGraphStore
from service.storage.analysis_store import get_analysis_report, list_analysis_report_summaries, save_analysis_report
from service.storage.job_store import create_job_record, finish_job_record, update_job_progress, update_job_repo, get_job_record
from service.storage.models import (
    AnalysisReportListResponse,
    AnalysisReportSummaryResponse,
    ChunkDetailResponse,
    EvidenceItem,
    FileDetailResponse,
    FileRecordResponse,
    IngestResponse,
    QARequest,
    QAResponse,
    RepoCreateRequest,
    RepoCreateResponse,
    RepoMapResponse,
    RepoResponse,
    RepoSummaryResponse,
    SearchRequest,
    SearchResponse,
    WorkflowAnalyzeRequest,
    WorkflowReportResponse,
    JobRecordResponse,
    JobListResponse,
)
from service.storage.repository_store import create_repo_record, get_file_record, get_repo_record, list_file_records, replace_file_records
from service.storage.session_store import create_session_record
from service.config.settings import get_settings

router = APIRouter(prefix="/repos", tags=["repos"])
analysis_router = APIRouter(tags=["analysis"])


def build_repo_response(record: dict) -> RepoResponse:
    """把数据库记录转换成 API 响应模型。"""
    return RepoResponse(
        repo_id=record["id"],
        alias=record["alias"],
        repo_path=record["repo_path"],
        remote_url=record["remote_url"],
        branch=record["branch"],
        current_commit=record["commit_hash"],
        status=record["status"],
        file_count=record["file_count"],
    )


@router.post("", response_model=RepoCreateResponse)
def create_repository(request: RepoCreateRequest) -> RepoCreateResponse:
    """注册本地 Git 仓库，并执行一次只读文件扫描。"""
    try:
        repo_path = resolve_repository_path(request.repo_path)
        validate_git_repository(repo_path)
    except RepositoryScanError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    branch = request.branch or get_current_branch(repo_path)
    current_commit = get_current_commit(repo_path)
    alias = request.alias or repo_path.name
    scanned_files = scan_repository_files(repo_path)

    repo_id = create_repo_record(
        repo_path=repo_path,
        alias=alias,
        remote_url=request.remote_url,
        branch=branch,
        current_commit=current_commit,
    )
    replace_file_records(repo_id, scanned_files)

    return RepoCreateResponse(
        repo_id=repo_id,
        status="registered",
        current_commit=current_commit,
        file_count=len(scanned_files),
    )


@router.get("/{repo_id}", response_model=RepoResponse)
def get_repository(repo_id: str) -> RepoResponse:
    """查询仓库基本信息。"""
    record = get_repo_record(repo_id)
    if record is None:
        raise HTTPException(status_code=404, detail="没有找到指定仓库。")
    return build_repo_response(record)


@router.get("/{repo_id}/files", response_model=list[FileRecordResponse])
def get_repository_files(repo_id: str, limit: int = 100) -> list[FileRecordResponse]:
    """查询仓库扫描后的文件记录。"""
    if get_repo_record(repo_id) is None:
        raise HTTPException(status_code=404, detail="没有找到指定仓库。")
    rows = list_file_records(repo_id, limit=limit)
    return [
        FileRecordResponse(
            id=row["id"],
            repo_id=row["repo_id"],
            relative_path=row["relative_path"],
            language=row["language"],
            file_type=row["file_type"],
            extension=row["extension"],
            size_bytes=row["size_bytes"],
            line_count=row["line_count"],
            is_binary=bool(row["is_binary"]),
            is_test_file=bool(row["is_test_file"]),
            ignored_reason=row["ignored_reason"],
            hash=row["hash"],
            parse_status=row["parse_status"],
        )
        for row in rows
    ]


def build_file_record_response(row: dict, content: str | None = None, content_truncated: bool = False) -> FileDetailResponse:
    """把文件记录转换成文件详情响应。"""
    return FileDetailResponse(
        id=row["id"],
        repo_id=row["repo_id"],
        relative_path=row["relative_path"],
        language=row["language"],
        file_type=row["file_type"],
        extension=row["extension"],
        size_bytes=row["size_bytes"],
        line_count=row["line_count"],
        is_binary=bool(row["is_binary"]),
        is_test_file=bool(row["is_test_file"]),
        ignored_reason=row["ignored_reason"],
        hash=row["hash"],
        parse_status=row["parse_status"],
        content=content,
        content_truncated=content_truncated,
    )


@router.get("/{repo_id}/files/{file_id}", response_model=FileDetailResponse)
def get_repository_file_detail(repo_id: str, file_id: str) -> FileDetailResponse:
    """读取单个文件记录和文本预览。"""
    get_required_repo_record(repo_id)
    record = get_file_record(repo_id, file_id)
    if record is None:
        raise HTTPException(status_code=404, detail="没有找到指定文件。")

    content = None
    content_truncated = False
    if record["file_type"] == "text" and record["ignored_reason"] is None:
        file_path = Path(record["absolute_path"])
        if file_path.exists() and file_path.is_file():
            raw_content = file_path.read_text(encoding="utf-8", errors="replace")
            content_truncated = len(raw_content) > 20000
            content = raw_content[:20000]
    return build_file_record_response(record, content=content, content_truncated=content_truncated)


@router.get("/{repo_id}/chunks/{chunk_id}", response_model=ChunkDetailResponse)
def get_repository_chunk_detail(repo_id: str, chunk_id: str) -> ChunkDetailResponse:
    """读取单个知识片段详情。"""
    get_required_repo_record(repo_id)
    record = get_chunk_record(repo_id, chunk_id)
    if record is None:
        raise HTTPException(status_code=404, detail="没有找到指定知识片段。")
    return ChunkDetailResponse(
        id=record["id"],
        repo_id=record["repo_id"],
        file_id=record["file_id"],
        file_path=record["file_path"],
        chunk_type=record["chunk_type"],
        title=record["title"],
        symbol_name=record["symbol_name"],
        start_line=record["start_line"],
        end_line=record["end_line"],
        content=record["content"],
        content_hash=record["content_hash"],
        token_count=record["token_count"],
        embedding_status=record["embedding_status"],
        source_type=record["source_type"],
        metadata_json=record["metadata_json"],
        parent_id=record["parent_id"],
    )


def get_required_repo_record(repo_id: str) -> dict:
    """读取仓库记录，不存在时抛出统一 HTTP 错误。"""
    record = get_repo_record(repo_id)
    if record is None:
        raise HTTPException(status_code=404, detail="没有找到指定仓库。")
    return record


@router.get("/{repo_id}/map", response_model=RepoMapResponse)
def get_repository_map(repo_id: str) -> RepoMapResponse:
    """生成仓库结构地图。"""
    record = get_required_repo_record(repo_id)
    repo_map = build_repo_map(record, list_file_records(repo_id, limit=5000), chunk_count=count_chunks(repo_id))
    return RepoMapResponse(**repo_map)


@router.get("/{repo_id}/summary", response_model=RepoSummaryResponse)
def get_repository_summary(repo_id: str) -> RepoSummaryResponse:
    """生成仓库概括性摘要。"""
    record = get_required_repo_record(repo_id)
    repo_map = build_repo_map(record, list_file_records(repo_id, limit=5000), chunk_count=count_chunks(repo_id))
    return RepoSummaryResponse(**build_repo_summary(repo_map))


def _run_ingest_task(job_id: str, repo_id: str, progress_callback):
    """在后台执行索引任务的逻辑。

    作用：解析所有文件、生成向量嵌入、构建知识图谱。
    原理：使用多线程并行处理文件解析和向量嵌入，大幅加速索引。
    参数：
        job_id: 任务ID
        repo_id: 仓库ID
        progress_callback: 进度回调函数，签名是 (progress: float, message: str) -> None
    """
    import logging as _log
    logger = _log.getLogger(__name__)

    record = get_required_repo_record(repo_id)
    files = list_indexable_file_records(repo_id)
    total_files = len(files)

    if total_files == 0:
        progress_callback(1.0, "没有可索引的文件")
        return

    # 阶段1：并行解析文件为知识片段 (40% 进度)
    # 使用多线程并行处理文件解析，I/O密集型操作可显著加速
    from service.core.parallel_ingest import parallel_parse_files
    chunks_by_file = parallel_parse_files(files, max_workers=4, progress_callback=progress_callback)

    # 阶段2：保存知识片段 (50% 进度)
    progress_callback(0.4, "保存知识片段...")
    chunk_count = replace_repo_chunks(repo_id, chunks_by_file)
    progress_callback(0.5, f"已保存 {chunk_count} 个知识片段")

    # 阶段3：并行构建向量索引 (80% 进度)
    progress_callback(0.5, "构建向量索引...")
    # 使用优化的并行 embedding 计算 + 批量插入
    from service.core.parallel_ingest import parallel_build_embeddings, batch_insert_embeddings
    from service.core.vector_store import list_chunk_texts
    chunks = list_chunk_texts(repo_id)
    embeddings = parallel_build_embeddings(chunks, max_workers=4, progress_callback=progress_callback)
    batch_insert_embeddings(repo_id, embeddings)
    progress_callback(0.8, "向量索引完成")

    # 阶段4：构建代码知识图谱 (100% 进度)
    progress_callback(0.8, "构建代码知识图谱...")
    try:
        settings = get_settings()
        graph_store = CodeGraphStore(settings.paths.database_path)
        builder = CodeGraphBuilder()
        graph = builder.build_from_directory(record["repo_path"])
        graph_store.save_graph(repo_id, graph)
        logger.info("代码图谱构建完成: %d 节点, %d 边", len(graph.nodes), len(graph.edges))
    except Exception as graph_exc:
        logger.warning("代码图谱构建失败(非关键): %s", graph_exc)

    progress_callback(1.0, f"索引完成: {total_files} 文件, {chunk_count} 片段")


@router.post("/{repo_id}/ingest", response_model=IngestResponse)
def ingest_repository(repo_id: str) -> IngestResponse:
    """启动异步索引任务，立即返回 job_id。

    作用：把耗时的索引操作放到后台执行，不阻塞API。
    原理：创建任务记录后立即返回，前端通过轮询 /jobs/{job_id} 获取进度。
    """
    get_required_repo_record(repo_id)
    files = list_file_records(repo_id, limit=5000)
    job_id = create_job_record("ingest", repo_id=repo_id, message="索引任务已提交")

    # 在后台线程中执行
    import threading
    def _do_ingest():
        try:
            _run_ingest_task(job_id, repo_id, lambda p, m=None: update_job_progress(job_id, p, m))
            finish_job_record(job_id, "succeeded", message="索引完成", progress=1.0)
        except Exception as exc:
            finish_job_record(job_id, "failed", message=str(exc), error=str(exc))

    threading.Thread(target=_do_ingest, daemon=True).start()

    return IngestResponse(
        repo_id=repo_id,
        status="indexing",
        indexed_file_count=len(files),
        chunk_count=count_chunks(repo_id),
        job_id=job_id,
    )


def ensure_repo_ingested(repo_id: str) -> None:
    """确保仓库至少完成一次 chunk/FTS 索引。

    作用：在需要索引数据前检查是否已索引，未索引时触发后台任务并等待完成。
    原理：如果已有 chunk 则直接返回；否则启动后台任务并轮询直到完成。
    注意：此函数仅在直接需要索引结果的同步场景下使用（如问答），会自动等待。
    """
    if count_chunks(repo_id) > 0:
        return

    # 启动异步索引
    job_id = create_job_record("ingest", repo_id=repo_id, message="自动索引中")
    import threading
    def _do_ingest():
        try:
            _run_ingest_task(job_id, repo_id, lambda p, m=None: update_job_progress(job_id, p, m))
            finish_job_record(job_id, "succeeded", message="索引完成", progress=1.0)
        except Exception as exc:
            finish_job_record(job_id, "failed", message=str(exc), error=str(exc))

    threading.Thread(target=_do_ingest, daemon=True).start()

    # 轮询等待，最多等10分钟（仅用于内部调用场景）
    import time
    for _ in range(600):
        record = get_job_record(job_id)
        if record and record["status"] in ("succeeded", "failed"):
            return
        time.sleep(1)


def build_snippet(content: str, max_length: int = 280) -> str:
    """把 chunk 内容压缩成适合证据面板展示的短片段。"""
    normalized = " ".join(content.split())
    if len(normalized) <= max_length:
        return normalized
    return f"{normalized[:max_length].rstrip()}..."


def build_evidence_items(rows: list[dict], repo_id: str) -> list[EvidenceItem]:
    """把搜索结果转换成证据展示模型。"""
    return [
        EvidenceItem(
            file_path=row["file_path"],
            chunk_id=row["chunk_id"],
            start_line=row.get("start_line"),
            end_line=row.get("end_line"),
            source_type=row.get("source_type", "unknown"),
            score=row.get("vector_score", 0.0),
            reason="语义匹配" if row.get("vector_score", 0) > 0 else "文本匹配",
            snippet=build_snippet(row.get("content", "")),
            title=row.get("title"),
            symbol_name=row.get("symbol_name"),
        )
        for row in rows
    ]


def _qa_evidence(repo_id: str, question: str) -> tuple[list[EvidenceItem], str]:
    """混合向量与关键词检索，收集问答证据。

    作用：把用户问题转换成多种检索方式，找到最相关的代码片段。
    原理：先做向量检索，再做关键词合并，去重后按分数排序取前N条。
    """
    vector_hits = search_vectors(repo_id, question) if count_chunks(repo_id) > 0 else []
    fts_hits = search_chunks(repo_id, question)

    repo_map = build_repo_map(get_required_repo_record(repo_id), list_file_records(repo_id, limit=5000), chunk_count=count_chunks(repo_id))
    repo_summary = build_repo_summary(repo_map)

    used_ids = set()
    merged = []
    for item in vector_hits + fts_hits:
        key = (item.get("chunk_id") or item.get("chunk_id"))
        if key in used_ids:
            continue
        used_ids.add(key)
        merged.append(item)

    if not merged:
        for chunk in list_indexable_file_records(repo_id)[:5]:
            pass

    return build_evidence_items(merged[:10], repo_id), repo_summary


def get_setting(key: str, default=None):
    """从 settings_store 读取单个配置项。"""
    from service.storage.settings_store import read_settings_dict
    return read_settings_dict().get(key, default)


@router.post("/{repo_id}/ask", response_model=QAResponse)
def ask_repository(repo_id: str, request: QARequest) -> QAResponse:
    """对仓库提问并返回 AI 回答。"""
    get_required_repo_record(repo_id)

    evidence, repo_summary = _qa_evidence(repo_id, request.question)
    answer_draft = answer_question(
        question=request.question,
        evidence=[item.model_dump() for item in evidence],
        repo_summary=repo_summary,
    )
    create_session_record(repo_id, request.question, answer_draft.answer, answer_draft.trace_id)

    # 估算费用：按输入/输出分别估算（粗估：输入占 70% token，输出占 30%）
    input_cost = get_setting("input_cost_per_1k_tokens", 0.0005) if get_setting("input_cost_per_1k_tokens") is not None else 0.0005
    output_cost = get_setting("output_cost_per_1k_tokens", 0.0015) if get_setting("output_cost_per_1k_tokens") is not None else 0.0015
    tokens = answer_draft.token_count
    estimated_cost = (tokens * 0.7 / 1000 * input_cost) + (tokens * 0.3 / 1000 * output_cost)

    return QAResponse(
        answer=answer_draft.answer,
        evidence=evidence,
        suggestions=[],
        confidence=answer_draft.confidence,
        used_context=answer_draft.used_context,
        trace_id=answer_draft.trace_id,
        next_steps=answer_draft.next_steps,
        token_count=answer_draft.token_count,
    )


@router.post("/{repo_id}/search", response_model=SearchResponse)
def search_repository(repo_id: str, request: SearchRequest) -> SearchResponse:
    """搜索仓库内容，返回匹配的证据列表。"""
    get_required_repo_record(repo_id)
    evidence, _ = _qa_evidence(repo_id, request.query)
    return SearchResponse(repo_id=repo_id, query=request.query, evidence=evidence)


@router.post("/{repo_id}/analysis/workflow", response_model=WorkflowReportResponse)
def analyze_existing_repository(repo_id: str, auto_ingest: bool = True) -> WorkflowReportResponse:
    """对已注册的仓库运行首次工作流分析。"""
    job_id = create_job_record("workflow_analysis", repo_id=repo_id, message="运行仓库工作流分析")
    try:
        record = get_required_repo_record(repo_id)
        if auto_ingest:
            ensure_repo_ingested(repo_id)
            record = get_required_repo_record(repo_id)
        files = list_file_records(repo_id, limit=10000)
        report = save_analysis_report(build_workflow_report(record, files))
        finish_job_record(job_id, "succeeded", message=f"生成工作流报告 {report['analysis_id']}")
        return WorkflowReportResponse(**report)
    except Exception as exc:
        finish_job_record(job_id, "failed", message="工作流分析失败", error=str(exc))
        raise


@router.get("/{repo_id}/analysis/reports", response_model=AnalysisReportListResponse)
def list_repository_analysis_reports(repo_id: str, limit: int = 12) -> AnalysisReportListResponse:
    """列出仓库最近的工作流分析报告。"""
    get_required_repo_record(repo_id)
    reports = list_analysis_report_summaries(repo_id, limit=max(1, min(limit, 50)))
    return AnalysisReportListResponse(
        repo_id=repo_id,
        reports=[AnalysisReportSummaryResponse(**item) for item in reports],
    )


@analysis_router.post("/analysis/analyze", response_model=WorkflowReportResponse)
@analysis_router.post("/analyze", response_model=WorkflowReportResponse, include_in_schema=False)
def analyze_repository(request: WorkflowAnalyzeRequest) -> WorkflowReportResponse:
    """从本地 repo_id 或公开 GitHub URL 启动工作流分析。"""
    if bool(request.repo_id) == bool(request.github_url):
        raise HTTPException(status_code=400, detail="请提供 repo_id 或 github_url，且只能提供其中一个。")

    repo_id = request.repo_id
    job_id = create_job_record("workflow_analysis", repo_id=repo_id, message="运行仓库工作流分析")
    try:
        if request.github_url:
            try:
                repo_path = clone_public_github_repo(request.github_url)
                repo_id = register_cloned_repository(repo_path, request.github_url, alias=request.alias)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        assert repo_id is not None
        update_job_repo(job_id, repo_id)
        record = get_required_repo_record(repo_id)
        if request.auto_ingest:
            ensure_repo_ingested(repo_id)
            record = get_required_repo_record(repo_id)
        files = list_file_records(repo_id, limit=10000)
        report = save_analysis_report(build_workflow_report(record, files))
        finish_job_record(job_id, "succeeded", message=f"生成工作流报告 {report['analysis_id']}")
        return WorkflowReportResponse(**report)
    except Exception as exc:
        finish_job_record(job_id, "failed", message="工作流分析失败", error=str(exc))
        raise


@analysis_router.get("/analysis/{analysis_id}", response_model=WorkflowReportResponse)
def get_saved_analysis_report(analysis_id: str) -> WorkflowReportResponse:
    """读取已经保存的完整工作流分析报告。"""
    report = get_analysis_report(analysis_id)
    if report is None:
        raise HTTPException(status_code=404, detail="没有找到指定分析报告。")
    return WorkflowReportResponse(**report)
