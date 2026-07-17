"""
这个文件负责仓库注册和基本信息查询接口。
它在整个框架里扮演"仓库接入API"的角色，让桌面端可以把本地 Git 仓库登记到系统中。
"""

from pathlib import Path
import hashlib
import re

from fastapi import APIRouter, HTTPException, Query

from service.core.ingest_service import ingest_repository_snapshot
from service.core.agent import AgentContext, run_main_agent
from service.core.evidence import EvidenceAssembler
from service.core.retrieval import HybridRetriever
from service.core.repo_scanner import (
    RepositoryScanError,
    get_current_branch,
    get_current_commit,
    resolve_repository_path,
    scan_repository_files,
    validate_git_repository,
    ensure_clean_worktree,
)
from service.core.repo_map import build_repo_map, build_repo_summary
from service.core.vector_store import search_vectors  # 兼容旧测试/扩展注入；M1 lexical-only 不调用
from service.core.workflow_analysis import build_workflow_report, clone_public_github_repo, register_cloned_repository
from service.storage.chunk_store import count_chunks, get_chunk_record, list_chunk_records, search_chunks
from service.storage.evidence_store import (
    list_evidence_units,
    list_parser_diagnostics,
    list_relations,
    list_symbols,
)
from service.storage.agent_trace_store import bind_trace_session, get_agent_trace
from service.storage.analysis_store import get_analysis_report, list_analysis_report_summaries, save_analysis_report
from service.storage.catalog_store import get_catalog_item, get_catalog_tree, list_catalog_items
from service.storage.job_store import create_job_record, finish_job_record, start_job_record, update_job_progress, update_job_repo, update_job_snapshot, get_job_record
from service.storage.models import (
    AnalysisReportListResponse,
    AnalysisReportSummaryResponse,
    CatalogItemResponse,
    CatalogListResponse,
    CatalogTreeResponse,
    ChunkDetailResponse,
    EvidenceItem,
    FileDetailResponse,
    FileRecordResponse,
    IngestResponse,
    ParserFactListResponse,
    QARequest,
    QAResponse,
    RepoCreateRequest,
    RepoCreateResponse,
    RepoMapResponse,
    RepoResponse,
    RepoSummaryResponse,
    SearchRequest,
    SearchResponse,
    SnapshotListResponse,
    SnapshotRefreshResponse,
    SnapshotResponse,
    WorkflowAnalyzeRequest,
    WorkflowRegistrationResponse,
    WorkflowReportResponse,
    JobRecordResponse,
    JobListResponse,
    LegacyWorkflowReportResponse,
)
from service.storage.repository_store import create_repo_record, find_repo_by_source, get_file_record, get_repo_record, list_file_records, list_repo_records, replace_file_records
from service.storage.snapshot_store import get_active_snapshot, get_snapshot, list_snapshots, stable_snapshot_id
from service.storage.session_store import create_session_record

router = APIRouter(prefix="/repos", tags=["repos"])
analysis_router = APIRouter(tags=["analysis"])


def resolve_product_snapshot(repo_id: str, snapshot_id: str | None = None) -> dict:
    """产品查询只允许 succeeded 快照；默认必须解析到 active succeeded。"""
    get_required_repo_record(repo_id)
    snapshot = get_snapshot(snapshot_id) if snapshot_id else get_active_snapshot(repo_id)
    if snapshot is None or snapshot["repo_id"] != repo_id:
        raise HTTPException(status_code=404, detail="没有找到指定快照。")
    if snapshot["status"] != "succeeded":
        raise HTTPException(status_code=409, detail="只有 succeeded 快照可以用于产品查询。")
    return snapshot


def _snapshot_context(repo_id: str, snapshot_id: str | None = None) -> dict | None:
    """快照管理接口允许查看任意状态，但仍拒绝跨仓库访问。"""
    snapshot = get_snapshot(snapshot_id) if snapshot_id else get_active_snapshot(repo_id)
    if snapshot is not None and snapshot["repo_id"] != repo_id:
        raise HTTPException(status_code=404, detail="没有找到指定快照。")
    if snapshot_id and snapshot is None:
        raise HTTPException(status_code=404, detail="没有找到指定快照。")
    return snapshot


def _build_snapshot_response(record: dict, active_snapshot_id: str | None = None) -> SnapshotResponse:
    """把数据库字段转换为对外稳定的 Snapshot 契约。"""
    return SnapshotResponse(
        snapshot_id=record["id"],
        repo_id=record["repo_id"],
        commit=record["commit_hash"],
        branch=record["branch"],
        status=record["status"],
        error=record["error"],
        is_active=record["id"] == active_snapshot_id,
        created_at=record["created_at"],
        updated_at=record.get("updated_at") or record["created_at"],
        finished_at=record.get("completed_at"),
    )


def build_repo_response(record: dict) -> RepoResponse:
    """把数据库记录转换成 API 响应模型，列表查询可直接复用 JOIN 结果。"""
    active_snapshot_id = record.get("active_snapshot_id")
    active_commit = record.get("active_commit_hash")
    if active_snapshot_id and active_commit is None:
        active_snapshot = get_active_snapshot(record["id"])
        active_commit = active_snapshot["commit_hash"] if active_snapshot else None
    return RepoResponse(
        repo_id=record["id"],
        alias=record["alias"],
        repo_path=record["repo_path"],
        remote_url=record["remote_url"],
        branch=record["branch"],
        current_commit=record["commit_hash"],
        status=record["status"],
        file_count=record["file_count"],
        snapshot_id=active_snapshot_id,
        commit=active_commit or record["commit_hash"],
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
    existing = find_repo_by_source(repo_path, request.remote_url)
    if existing is not None:
        return RepoCreateResponse(
            repo_id=existing["id"], status=existing["status"],
            current_commit=existing["commit_hash"], file_count=existing["file_count"],
        )
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


@router.get("", response_model=list[RepoResponse])
def list_repositories(limit: int = Query(default=100, ge=1, le=500)) -> list[RepoResponse]:
    """列出已注册仓库；旧的 POST /repos 注册契约保持不变。"""
    return [build_repo_response(record) for record in list_repo_records(limit=limit)]


@router.get("/{repo_id}", response_model=RepoResponse)
def get_repository(repo_id: str) -> RepoResponse:
    """查询仓库基本信息。"""
    record = get_repo_record(repo_id)
    if record is None:
        raise HTTPException(status_code=404, detail="没有找到指定仓库。")
    return build_repo_response(record)


@router.get("/{repo_id}/snapshots", response_model=SnapshotListResponse)
def list_repository_snapshots(repo_id: str, limit: int = Query(default=100, ge=1, le=500)) -> SnapshotListResponse:
    """列出仓库的历史快照，并标记当前 active 快照。"""
    record = get_required_repo_record(repo_id)
    active_snapshot_id = record.get("active_snapshot_id")
    return SnapshotListResponse(
        repo_id=repo_id,
        active_snapshot_id=active_snapshot_id,
        snapshots=[
            _build_snapshot_response(item, active_snapshot_id)
            for item in list_snapshots(repo_id, limit=limit)
        ],
    )


@router.get("/{repo_id}/snapshots/{snapshot_id}", response_model=SnapshotResponse)
def get_repository_snapshot(repo_id: str, snapshot_id: str) -> SnapshotResponse:
    """读取属于指定仓库的一条快照详情。"""
    record = get_required_repo_record(repo_id)
    snapshot = _snapshot_context(repo_id, snapshot_id)
    assert snapshot is not None
    return _build_snapshot_response(snapshot, record.get("active_snapshot_id"))


@router.post("/{repo_id}/refresh", response_model=SnapshotRefreshResponse, status_code=202)
def refresh_repository(repo_id: str) -> SnapshotRefreshResponse:
    """重新扫描当前 Git 提交并启动快照索引；具体索引仍复用 ingest 任务。"""
    record = get_required_repo_record(repo_id)
    repo_path = resolve_repository_path(record["repo_path"])
    try:
        validate_git_repository(repo_path)
    except RepositoryScanError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        ensure_clean_worktree(repo_path)
        current_commit = get_current_commit(repo_path)
        if not current_commit:
            raise RepositoryScanError("仓库还没有任何 commit，无法刷新不可变快照。")
        current_branch = get_current_branch(repo_path)
    except RepositoryScanError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    snapshot_id = stable_snapshot_id(repo_id, current_commit)
    job_id = _submit_ingest(repo_id, "刷新索引任务已提交", current_commit, current_branch)
    return SnapshotRefreshResponse(
        repo_id=repo_id, snapshot_id=snapshot_id, commit=current_commit,
        status="indexing", job_id=job_id,
    )


@router.get("/{repo_id}/files", response_model=list[FileRecordResponse])
def get_repository_files(repo_id: str, limit: int = Query(default=100, ge=1, le=1000), snapshot_id: str | None = None) -> list[FileRecordResponse]:
    """查询指定 succeeded 快照的文件记录。"""
    snapshot = resolve_product_snapshot(repo_id, snapshot_id)
    rows = list_file_records(repo_id, limit=limit, snapshot_id=snapshot["id"])
    return [
        FileRecordResponse(
            id=row["id"],
            repo_id=row["repo_id"],
            snapshot_id=snapshot["id"],
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
        snapshot_id=row.get("snapshot_id") or "legacy",
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
def get_repository_file_detail(repo_id: str, file_id: str, snapshot_id: str | None = None) -> FileDetailResponse:
    """读取文件元数据；文本预览只在当前 active 内容哈希一致时开放。"""
    repo = get_required_repo_record(repo_id)
    snapshot = resolve_product_snapshot(repo_id, snapshot_id)
    selected = snapshot["id"]
    record = get_file_record(repo_id, file_id, snapshot_id=selected)
    if record is None:
        raise HTTPException(status_code=404, detail="没有找到指定文件。")
    if snapshot_id and snapshot_id != repo.get("active_snapshot_id"):
        raise HTTPException(status_code=409, detail="历史快照文件不能从当前工作树预览，请使用该快照的 chunk/evidence 内容。")

    content = None
    content_truncated = False
    if record["file_type"] == "text" and record["ignored_reason"] is None:
        file_path = Path(record["absolute_path"])
        if file_path.exists() and file_path.is_file():
            raw_bytes = file_path.read_bytes()
            actual_hash = hashlib.sha1(raw_bytes).hexdigest()
            if record.get("hash") and actual_hash != record["hash"]:
                raise HTTPException(status_code=409, detail="当前工作树文件已与 active 快照不一致，拒绝返回错误版本预览。")
            raw_content = raw_bytes.decode("utf-8", errors="replace")
            content_truncated = len(raw_content) > 20000
            content = raw_content[:20000]
    return build_file_record_response(record, content=content, content_truncated=content_truncated)


@router.get("/{repo_id}/chunks/{chunk_id}", response_model=ChunkDetailResponse)
def get_repository_chunk_detail(repo_id: str, chunk_id: str, snapshot_id: str | None = None) -> ChunkDetailResponse:
    """读取 succeeded 快照中的单个知识片段详情。"""
    snapshot = resolve_product_snapshot(repo_id, snapshot_id)
    record = get_chunk_record(repo_id, chunk_id, snapshot_id=snapshot["id"])
    if record is None:
        raise HTTPException(status_code=404, detail="没有找到指定知识片段。")
    return ChunkDetailResponse(
        id=record["id"],
        repo_id=record["repo_id"],
        snapshot_id=snapshot["id"],
        file_id=record.get("file_id") or "",
        file_path=record.get("file_path") or "",
        chunk_type=record.get("chunk_type") or "text",
        title=record["title"],
        symbol_name=record["symbol_name"],
        start_line=record["start_line"],
        end_line=record["end_line"],
        content=record.get("content") or "",
        content_hash=record.get("content_hash") or "",
        token_count=record.get("token_count"),
        embedding_status=record.get("embedding_status") or "pending",
        source_type=record.get("source_type") or "text",
        metadata_json=record["metadata_json"],
        parent_id=record["parent_id"],
    )


@router.get("/{repo_id}/evidence", response_model=ParserFactListResponse)
def get_repository_evidence(repo_id: str, snapshot_id: str | None = None, file_id: str | None = None,
                            query: str | None = None, limit: int = Query(default=100, ge=1, le=1000)) -> ParserFactListResponse:
    """查询规范 Evidence 事实。"""
    snapshot = resolve_product_snapshot(repo_id, snapshot_id)
    return ParserFactListResponse(repo_id=repo_id, snapshot_id=snapshot["id"], items=list_evidence_units(
        repo_id, snapshot_id=snapshot["id"], file_id=file_id, query=query, limit=limit,
    ))


@router.get("/{repo_id}/symbols", response_model=ParserFactListResponse)
def get_repository_symbols(repo_id: str, snapshot_id: str | None = None, query: str | None = None,
                           limit: int = Query(default=100, ge=1, le=1000)) -> ParserFactListResponse:
    """查询规范 Symbol 事实。"""
    snapshot = resolve_product_snapshot(repo_id, snapshot_id)
    return ParserFactListResponse(repo_id=repo_id, snapshot_id=snapshot["id"], items=list_symbols(
        repo_id, snapshot_id=snapshot["id"], query=query, limit=limit,
    ))


@router.get("/{repo_id}/relations", response_model=ParserFactListResponse)
def get_repository_relations(repo_id: str, snapshot_id: str | None = None,
                             limit: int = Query(default=1000, ge=1, le=5000)) -> ParserFactListResponse:
    """查询规范 Relation 事实，包括未解析关系。"""
    snapshot = resolve_product_snapshot(repo_id, snapshot_id)
    return ParserFactListResponse(repo_id=repo_id, snapshot_id=snapshot["id"], items=list_relations(
        repo_id, snapshot_id=snapshot["id"], limit=limit,
    ))


@router.get("/{repo_id}/parser-diagnostics", response_model=ParserFactListResponse)
def get_repository_parser_diagnostics(repo_id: str, snapshot_id: str | None = None,
                                      file_id: str | None = None, limit: int = Query(default=1000, ge=1, le=5000)) -> ParserFactListResponse:
    """查询解析 fallback、语法错误和 linker 诊断。"""
    snapshot = resolve_product_snapshot(repo_id, snapshot_id)
    return ParserFactListResponse(repo_id=repo_id, snapshot_id=snapshot["id"], items=list_parser_diagnostics(
        repo_id, snapshot_id=snapshot["id"], file_id=file_id, limit=limit,
    ))


@router.get("/{repo_id}/catalog", response_model=CatalogListResponse)
def get_repository_catalog(repo_id: str, snapshot_id: str | None = None,
                           kind: str | None = None) -> CatalogListResponse:
    """列出指定 succeeded 快照的 Catalog；默认读取 active 快照。"""
    snapshot = resolve_product_snapshot(repo_id, snapshot_id)
    return CatalogListResponse(
        repo_id=repo_id,
        snapshot_id=snapshot["id"],
        items=[CatalogItemResponse(**item) for item in list_catalog_items(repo_id, snapshot["id"], kind)],
    )


@router.get("/{repo_id}/catalog/tree", response_model=CatalogTreeResponse)
def get_repository_catalog_tree(repo_id: str, snapshot_id: str | None = None) -> CatalogTreeResponse:
    """返回 Repository Catalog 的导航树。"""
    snapshot = resolve_product_snapshot(repo_id, snapshot_id)
    return CatalogTreeResponse(
        repo_id=repo_id,
        snapshot_id=snapshot["id"],
        roots=get_catalog_tree(repo_id, snapshot["id"]),
    )


@router.get("/{repo_id}/catalog/{item_id}", response_model=CatalogItemResponse)
def get_repository_catalog_detail(repo_id: str, item_id: str,
                                  snapshot_id: str | None = None) -> CatalogItemResponse:
    """读取单张 Catalog 卡片，显式快照时严格隔离。"""
    snapshot = resolve_product_snapshot(repo_id, snapshot_id)
    item = get_catalog_item(repo_id, snapshot["id"], item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="没有找到指定 Catalog 卡片。")
    return CatalogItemResponse(**item)


def get_required_repo_record(repo_id: str) -> dict:
    """读取仓库记录，不存在时抛出统一 HTTP 错误。"""
    record = get_repo_record(repo_id)
    if record is None:
        raise HTTPException(status_code=404, detail="没有找到指定仓库。")
    return record


@router.get("/{repo_id}/map", response_model=RepoMapResponse)
def get_repository_map(repo_id: str, snapshot_id: str | None = None) -> RepoMapResponse:
    """生成仓库结构地图；不传快照时默认使用 active。"""
    record, snapshot, repo_map = _repo_map_context(repo_id, snapshot_id)
    return RepoMapResponse(
        **repo_map,
        snapshot_id=snapshot["id"] if snapshot else None,
        commit=snapshot["commit_hash"] if snapshot else record["commit_hash"],
    )


@router.get("/{repo_id}/summary", response_model=RepoSummaryResponse)
def get_repository_summary(repo_id: str, snapshot_id: str | None = None) -> RepoSummaryResponse:
    """生成仓库概括性摘要；不传快照时默认使用 active。"""
    record, snapshot, repo_map = _repo_map_context(repo_id, snapshot_id)
    return RepoSummaryResponse(
        **build_repo_summary(repo_map),
        snapshot_id=snapshot["id"] if snapshot else None,
        commit=snapshot["commit_hash"] if snapshot else record["commit_hash"],
    )


def _repo_map_context(repo_id: str, snapshot_id: str | None = None) -> tuple[dict, dict, dict]:
    """一次解析 succeeded 快照并构建 map，供 map/summary/QA 复用。"""
    record = get_required_repo_record(repo_id)
    snapshot = resolve_product_snapshot(repo_id, snapshot_id)
    selected = snapshot["id"]
    repo_map = build_repo_map(
        record,
        list_file_records(repo_id, limit=5000, snapshot_id=selected),
        chunk_count=count_chunks(repo_id, selected),
    )
    return record, snapshot, repo_map


def _submit_ingest(repo_id: str, message: str, expected_commit: str | None = None,
                   expected_branch: str | None = None) -> str:
    """统一创建和运行后台 ingest，确保两条入口拥有相同任务生命周期。"""
    job_id = create_job_record("ingest", repo_id=repo_id, message=message)
    import threading

    def run() -> None:
        try:
            if not start_job_record(job_id, "正在索引仓库"):
                return
            result = ingest_repository_snapshot(
                repo_id,
                progress_callback=lambda progress, text=None: update_job_progress(job_id, progress, text),
                expected_commit=expected_commit,
                expected_branch=expected_branch,
            )
            update_job_snapshot(job_id, result.snapshot_id)
            finish_job_record(job_id, "succeeded", message="索引完成", progress=1.0)
        except Exception as exc:
            finish_job_record(job_id, "failed", message=str(exc), error=str(exc))

    threading.Thread(target=run, daemon=True).start()
    return job_id


@router.post("/{repo_id}/ingest", response_model=IngestResponse)
def ingest_repository(repo_id: str) -> IngestResponse:
    """启动异步索引任务，立即返回 job_id。"""
    get_required_repo_record(repo_id)
    files = list_file_records(repo_id, limit=5000)
    job_id = _submit_ingest(repo_id, "索引任务已提交")
    return IngestResponse(repo_id=repo_id, status="indexing", indexed_file_count=len(files),
                          chunk_count=count_chunks(repo_id), job_id=job_id)


def ensure_repo_ingested(repo_id: str) -> None:
    """确保存在 succeeded active 快照；失败、中断、取消和超时都向调用方抛错。"""
    if get_active_snapshot(repo_id) is not None:
        return
    job_id = _submit_ingest(repo_id, "自动索引中")
    import time
    for _ in range(600):
        record = get_job_record(job_id)
        if record and record["status"] == "succeeded":
            return
        if record and record["status"] in ("failed", "cancelled", "interrupted"):
            raise RuntimeError(record.get("error") or record.get("message") or f"索引任务{record['status']}")
        time.sleep(1)
    raise TimeoutError("等待仓库索引超时")


def build_snippet(content: str, max_length: int = 280) -> str:
    """把 chunk 内容压缩成适合证据面板展示的短片段。"""
    normalized = " ".join(content.split())
    if len(normalized) <= max_length:
        return normalized
    return f"{normalized[:max_length].rstrip()}..."


def build_evidence_items(rows: list[dict]) -> list[EvidenceItem]:
    """把搜索结果转换成证据展示模型，并如实标记结果来自哪种检索。"""
    return [
        EvidenceItem(
            # Main Agent 的 EvidenceBundle 使用 path 字段；兼容旧的 file_path/relative_path 投影。
            file_path=row.get("file_path") or row.get("path") or row.get("relative_path") or "",
            chunk_id=row.get("chunk_id") or row.get("id") or "",
            start_line=row.get("start_line"),
            end_line=row.get("end_line"),
            source_type=row.get("source_type", "unknown"),
            score=float(row.get("score", row.get("vector_score", 0.0))),
            reason=str(row.get("reason") or ("语义匹配" if row.get("match_type") == "semantic" else "文本匹配")),
            snippet=build_snippet(row.get("content", "")),
            title=row.get("title"),
            symbol_name=row.get("symbol_name"),
        )
        for row in rows
    ]


def _qa_evidence(repo_id: str, question: str, limit: int, snapshot_id: str,
                 commit: str) -> tuple[list[EvidenceItem], dict]:
    """执行混合检索，并把 Token 预算后的 Evidence Bundle 投影为旧响应。"""
    retrieval = HybridRetriever().retrieve(repo_id, snapshot_id, question, limit)
    bundle = EvidenceAssembler().assemble(retrieval.items, commit=commit, limit=limit)

    repo_map = build_repo_map(
        get_required_repo_record(repo_id),
        list_file_records(repo_id, limit=5000, snapshot_id=snapshot_id),
        chunk_count=count_chunks(repo_id, snapshot_id),
    )
    repo_summary = build_repo_summary(repo_map)
    rows = [
        {
            "id": item.chunk_id,
            "chunk_id": item.chunk_id,
            "file_path": item.path,
            "start_line": item.start_line,
            "end_line": item.end_line,
            "source_type": item.source_type,
            "score": item.score,
            "reason": item.reason,
            "content": item.content,
            "title": item.title,
            "symbol_name": item.symbol_name,
        }
        for item in bundle.items
    ]
    return build_evidence_items(rows), repo_summary



@router.post("/{repo_id}/ask", response_model=QAResponse)
def ask_repository(repo_id: str, request: QARequest) -> QAResponse:
    """对仓库提问；内部由 Main Agent 按需调用 Specialist Tools。"""
    record = get_required_repo_record(repo_id)
    snapshot = resolve_product_snapshot(repo_id, request.snapshot_id)
    result = run_main_agent(AgentContext(
        repo_id=repo_id,
        snapshot_id=snapshot["id"],
        commit=snapshot["commit_hash"],
        question=request.question,
        limit=request.limit,
    ))
    evidence = build_evidence_items(result.evidence)
    session_id = create_session_record(
        repo_id, request.question, result.answer, result.trace_id, snapshot["id"]
    )
    bind_trace_session(result.trace_id, session_id)

    return QAResponse(
        answer=result.answer,
        evidence=evidence,
        suggestions=[],
        confidence=result.confidence,
        used_context=result.used_context,
        trace_id=result.trace_id,
        next_steps=result.next_steps,
        token_count=result.token_count,
        snapshot_id=snapshot["id"],
        commit=snapshot["commit_hash"] or record["commit_hash"],
    )


@router.post("/{repo_id}/search", response_model=SearchResponse)
def search_repository(repo_id: str, request: SearchRequest) -> SearchResponse:
    """搜索仓库内容；旧客户端自动使用 active 快照。"""
    record = get_required_repo_record(repo_id)
    snapshot = resolve_product_snapshot(repo_id, request.snapshot_id)
    evidence, _ = _qa_evidence(
        repo_id, request.query, request.limit, snapshot["id"], snapshot["commit_hash"]
    )
    return SearchResponse(
        repo_id=repo_id,
        query=request.query,
        evidence=evidence,
        snapshot_id=snapshot["id"] if snapshot else None,
        commit=snapshot["commit_hash"] if snapshot else record["commit_hash"],
    )


@router.get("/{repo_id}/traces/{trace_id}")
def get_repository_agent_trace(repo_id: str, trace_id: str) -> dict:
    """读取 Main Agent 的真实执行轨迹。"""
    get_required_repo_record(repo_id)
    trace = get_agent_trace(repo_id, trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="没有找到指定 Agent Trace。")
    return trace


def _reconstruct_snapshot_file(chunks: list[dict]) -> tuple[str, bool]:
    """只在 chunks 保存的是原始源码切片时重建；结构化配置证据不得冒充精确源码。"""
    if not chunks:
        return "", False
    transformed_types = {"config_object", "config_value"}
    if any((item.get("chunk_type") or item.get("source_type")) in transformed_types for item in chunks):
        return "\n".join(item.get("content") or "" for item in chunks), False

    positioned = [item for item in chunks if isinstance(item.get("start_line"), int) and item["start_line"] > 0]
    if len(positioned) != len(chunks):
        return "\n".join(item.get("content") or "" for item in chunks), False

    lines: list[str] = []
    for chunk in sorted(positioned, key=lambda item: item["start_line"]):
        start_index = chunk["start_line"] - 1
        content_lines = (chunk.get("content") or "").splitlines()
        if len(lines) < start_index:
            lines.extend([""] * (start_index - len(lines)))
        for offset, line in enumerate(content_lines):
            target_index = start_index + offset
            if target_index < len(lines):
                # 重叠 chunk 可能重复同一源码行；保留先写入的内容，空占位才由后续 chunk 补齐。
                if not lines[target_index]:
                    lines[target_index] = line
            else:
                lines.append(line)
    return "\n".join(lines), True


def _workflow_snapshot_files(repo_id: str, snapshot_id: str) -> list[dict]:
    """分页组合快照文件与全部持久化 chunk，避免大快照被固定上限静默截断。"""
    page_size = 5000
    files: list[dict] = []
    file_offset = 0
    while True:
        page = list_file_records(
            repo_id,
            limit=page_size,
            snapshot_id=snapshot_id,
            offset=file_offset,
        )
        files.extend(page)
        if len(page) < page_size:
            break
        file_offset += len(page)

    chunks_by_path: dict[str, list[dict]] = {}
    offset = 0
    while True:
        page = list_chunk_records(repo_id, limit=page_size, snapshot_id=snapshot_id, offset=offset)
        for chunk in page:
            chunks_by_path.setdefault(chunk.get("file_path") or "", []).append(chunk)
        if len(page) < page_size:
            break
        offset += len(page)
    for file_record in files:
        chunks = sorted(chunks_by_path.get(file_record["relative_path"], []), key=lambda item: item.get("start_line") or 0)
        snapshot_content, source_exact = _reconstruct_snapshot_file(chunks)
        file_record["snapshot_content"] = snapshot_content
        file_record["snapshot_source_exact"] = source_exact
        file_record["snapshot_chunks"] = chunks
    return files


@router.post("/{repo_id}/analysis/workflow", response_model=WorkflowReportResponse)
def analyze_existing_repository(repo_id: str, auto_ingest: bool = True, snapshot_id: str | None = None) -> WorkflowReportResponse:
    """对已注册仓库的指定 succeeded 快照运行工作流分析。"""
    job_id = create_job_record("workflow_analysis", repo_id=repo_id, message="运行仓库工作流分析")
    try:
        start_job_record(job_id, "正在运行仓库工作流分析")
        record = get_required_repo_record(repo_id)
        # 旧客户端不传 snapshot_id 时仍可自动索引；显式历史快照不能被自动索引替换。
        if auto_ingest and snapshot_id is None:
            ensure_repo_ingested(repo_id)
            record = get_required_repo_record(repo_id)
        snapshot = resolve_product_snapshot(repo_id, snapshot_id)
        files = _workflow_snapshot_files(repo_id, snapshot["id"])
        report = save_analysis_report(
            build_workflow_report(record, files, snapshot_id=snapshot["id"], commit=snapshot["commit_hash"]),
            snapshot_id=snapshot["id"],
        )
        finish_job_record(job_id, "succeeded", message=f"生成工作流报告 {report['analysis_id']}")
        return WorkflowReportResponse(**report)
    except Exception as exc:
        finish_job_record(job_id, "failed", message="工作流分析失败", error=str(exc))
        raise


@router.get("/{repo_id}/analysis/reports", response_model=AnalysisReportListResponse)
def list_repository_analysis_reports(repo_id: str, limit: int = Query(default=12, ge=1, le=50)) -> AnalysisReportListResponse:
    """列出仓库最近的工作流分析报告。"""
    get_required_repo_record(repo_id)
    reports = list_analysis_report_summaries(repo_id, limit=max(1, min(limit, 50)))
    return AnalysisReportListResponse(
        repo_id=repo_id,
        reports=[AnalysisReportSummaryResponse(**item) for item in reports],
    )


@analysis_router.post("/analysis/analyze", response_model=WorkflowReportResponse | WorkflowRegistrationResponse)
@analysis_router.post("/analyze", response_model=WorkflowReportResponse | WorkflowRegistrationResponse, include_in_schema=False)
def analyze_repository(request: WorkflowAnalyzeRequest) -> WorkflowReportResponse | WorkflowRegistrationResponse:
    """从本地 repo_id 或公开 GitHub URL 启动工作流分析。"""
    if bool(request.repo_id) == bool(request.github_url):
        raise HTTPException(status_code=400, detail="请提供 repo_id 或 github_url，且只能提供其中一个。")

    repo_id = request.repo_id
    job_id = create_job_record("workflow_analysis", repo_id=repo_id, message="运行仓库工作流分析")
    try:
        start_job_record(job_id, "正在运行仓库工作流分析")
        if request.github_url:
            try:
                repo_path = clone_public_github_repo(request.github_url)
                repo_id = register_cloned_repository(repo_path, request.github_url, alias=request.alias)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        assert repo_id is not None
        update_job_repo(job_id, repo_id)
        record = get_required_repo_record(repo_id)
        # 关闭自动索引时，已有 active succeeded 快照仍应被分析；只有首次登记且无快照才返回登记契约。
        active_snapshot = get_active_snapshot(repo_id) if request.snapshot_id is None else None
        if not request.auto_ingest and request.snapshot_id is None and active_snapshot is None:
            finish_job_record(job_id, "succeeded", message=f"仓库已登记 {repo_id}")
            return WorkflowRegistrationResponse(
                repo_id=repo_id,
                current_commit=record["commit_hash"],
                file_count=len(list_file_records(repo_id, limit=10000)),
            )
        # GitHub 首次登记没有历史快照，只在未指定快照时自动建立 active。
        if request.auto_ingest and request.snapshot_id is None:
            ensure_repo_ingested(repo_id)
            record = get_required_repo_record(repo_id)
        snapshot = resolve_product_snapshot(repo_id, request.snapshot_id)
        files = _workflow_snapshot_files(repo_id, snapshot["id"])
        report = save_analysis_report(
            build_workflow_report(record, files, snapshot_id=snapshot["id"], commit=snapshot["commit_hash"]),
            snapshot_id=snapshot["id"],
        )
        finish_job_record(job_id, "succeeded", message=f"生成工作流报告 {report['analysis_id']}")
        return WorkflowReportResponse(**report)
    except Exception as exc:
        finish_job_record(job_id, "failed", message="工作流分析失败", error=str(exc))
        raise


@analysis_router.get("/analysis/{analysis_id}", response_model=LegacyWorkflowReportResponse)
def get_saved_analysis_report(analysis_id: str) -> LegacyWorkflowReportResponse:
    """读取已经保存的完整工作流分析报告。"""
    report = get_analysis_report(analysis_id)
    if report is None:
        raise HTTPException(status_code=404, detail="没有找到指定分析报告。")
    return LegacyWorkflowReportResponse(**report)
