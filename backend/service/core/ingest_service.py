"""
这个文件实现不可变 Snapshot 的生产 ingest 流水线。
扫描结果只负责捕获文件身份；统一 ParserRegistry 产生规范事实，chunks 和 code graph 都只是兼容投影。
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
import hashlib
from pathlib import Path
import threading

from service.core.embeddings.service import embed_snapshot_evidence
from service.core.catalog.builder import build_catalog
from service.core.parsing import Diagnostic, SourceDocument, default_registry
from service.storage.evidence_store import (
    list_evidence_units,
    list_symbols,
    project_evidence_to_chunks,
    replace_all_snapshot_parse_results,
)
from service.storage.catalog_store import replace_snapshot_catalog
from service.storage.symbol_store import project_symbols_to_code_graph
from service.core.repo_scanner import (
    RepositoryScanError,
    decode_text_content,
    ensure_clean_worktree,
    get_current_branch,
    get_current_commit,
    scan_repository_files,
)
from service.storage.chunk_store import count_chunks, list_indexable_file_records
from service.storage.repository_store import get_repo_record, replace_file_records
from service.storage.snapshot_store import (
    fail_snapshot,
    get_or_create_snapshot,
    publish_snapshot,
    retry_failed_snapshot,
    set_active_snapshot,
)
from service.storage.sqlite_db import get_connection

_LOCKS_GUARD = threading.Lock()
_REPO_LOCKS: dict[str, threading.Lock] = {}


@contextmanager
def _repo_lock(repo_id: str):
    """为同一 repo_id 提供进程内串行化，避免不同 SHA 反序发布。"""
    with _LOCKS_GUARD:
        lock = _REPO_LOCKS.setdefault(repo_id, threading.Lock())
    lock.acquire()
    try:
        yield
    finally:
        lock.release()


@dataclass(frozen=True)
class IngestResult:
    repo_id: str
    snapshot_id: str
    commit_hash: str
    status: str
    indexed_file_count: int
    chunk_count: int
    reused: bool = False
    embedding_status: str = "disabled"
    embedding_warning: str | None = None


def _clear_failed_snapshot(repo_id: str, snapshot_id: str) -> None:
    """按外键依赖顺序清理失败快照全部产物，保证重试不受残留事实影响。"""
    with get_connection() as connection:
        for table in (
            "catalog_items", "evidence_embeddings", "vectors", "code_edges", "code_nodes", "code_graph_diagnostics", "chunks",
            "parser_diagnostics", "relations", "symbols", "evidence_units", "files",
        ):
            connection.execute(f"DELETE FROM {table} WHERE repo_id = ? AND snapshot_id = ?" if table not in {
                "parser_diagnostics", "relations", "symbols", "evidence_units"
            } else f"DELETE FROM {table} WHERE snapshot_id = ?", (repo_id, snapshot_id) if table not in {
                "parser_diagnostics", "relations", "symbols", "evidence_units"
            } else (snapshot_id,))


def _capture_documents(repo_id: str, snapshot_id: str, files: list[dict], captured: dict[str, bytes] | None = None) -> list[SourceDocument]:
    """从已持久化扫描结果读取一次源码并校验扫描哈希，任何 I/O 或漂移都中止发布。"""
    documents: list[SourceDocument] = []
    for item in files:
        path = Path(item["absolute_path"])
        raw = (captured or {}).get(item["relative_path"])
        if raw is None:
            raw = path.read_bytes()
        if hashlib.sha1(raw).hexdigest() != item.get("hash"):
            raise RepositoryScanError(f"扫描后文件内容已变化：{item['relative_path']}")
        try:
            content = decode_text_content(raw)
        except UnicodeDecodeError as exc:
            raise RepositoryScanError(f"文本文件无法按支持的编码读取：{item['relative_path']}") from exc
        documents.append(SourceDocument(
            repo_id=repo_id,
            snapshot_id=snapshot_id,
            file_id=item["id"],
            path=item["relative_path"],
            content=content,
            raw_bytes=raw,
            language=item.get("language"),
            metadata={"absolute_path": item["absolute_path"], "is_test_file": bool(item.get("is_test_file"))},
        ))
    return documents


def _normalize_parse_result(result):
    """补齐快照/文件归属，解析器只需专注产生语言事实。"""
    document = result.document
    result.evidence = [replace(item, snapshot_id=document.snapshot_id, file_id=document.file_id) for item in result.evidence]
    result.symbols = [replace(item, snapshot_id=document.snapshot_id, file_id=document.file_id) for item in result.symbols]
    result.relations = [replace(item, snapshot_id=document.snapshot_id, file_id=document.file_id) for item in result.relations]
    result.diagnostics = [replace(
        item, snapshot_id=document.snapshot_id, file_id=document.file_id,
        parser=item.parser or "unknown",
    ) for item in result.diagnostics]
    result.sort_facts()
    return result


def _update_parse_statuses(repo_id: str, snapshot_id: str, results: list) -> None:
    """让每个可索引文件最终落入统一五态之一。"""
    statuses = {result.document.file_id: result.status for result in results}
    allowed = {"parsed", "parsed_with_errors", "fallback_text", "unsupported", "failed"}
    with get_connection() as connection:
        for file_id, status in statuses.items():
            if status not in allowed:
                raise ValueError(f"非法 parse_status：{status}")
            connection.execute(
                "UPDATE files SET parse_status = ? WHERE id = ? AND repo_id = ? AND snapshot_id = ?",
                (status, file_id, repo_id, snapshot_id),
            )
        pending = connection.execute(
            """SELECT COUNT(*) FROM files WHERE repo_id = ? AND snapshot_id = ?
               AND ignored_reason IS NULL AND file_type = 'text' AND is_binary = 0
               AND parse_status NOT IN ('parsed','parsed_with_errors','fallback_text','unsupported','failed')""",
            (repo_id, snapshot_id),
        ).fetchone()[0]
        if pending:
            raise RuntimeError(f"仍有 {pending} 个可索引文件没有解析结果")


def _validate_snapshot(repo_id: str, snapshot_id: str, expected_files: int, expected_chunks: int) -> None:
    """发布前检查计数、投影完整性和 SQLite 外键。"""
    with get_connection() as connection:
        file_count = connection.execute(
            "SELECT COUNT(*) FROM files WHERE repo_id = ? AND snapshot_id = ?", (repo_id, snapshot_id)
        ).fetchone()[0]
        evidence_count = connection.execute(
            "SELECT COUNT(*) FROM evidence_units WHERE snapshot_id = ?", (snapshot_id,)
        ).fetchone()[0]
        chunk_count = connection.execute(
            "SELECT COUNT(*) FROM chunks WHERE repo_id = ? AND snapshot_id = ?", (repo_id, snapshot_id)
        ).fetchone()[0]
        vector_count = connection.execute(
            "SELECT COUNT(*) FROM evidence_embeddings WHERE repo_id = ? AND snapshot_id = ?", (repo_id, snapshot_id)
        ).fetchone()[0]
        embedding_statuses = {
            str(row[0]) for row in connection.execute(
                "SELECT DISTINCT embedding_status FROM chunks WHERE repo_id = ? AND snapshot_id = ?",
                (repo_id, snapshot_id),
            ).fetchall()
        }
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    if file_count != expected_files or chunk_count != expected_chunks or evidence_count != chunk_count:
        raise RuntimeError("快照事实或投影计数校验失败")
    if "ready" in embedding_statuses and vector_count != chunk_count:
        raise RuntimeError("Embedding 状态为 ready 时向量数量与 Evidence 不一致")
    if violations:
        raise RuntimeError(f"快照外键校验失败：{len(violations)}")


def ingest_repository_snapshot(repo_id: str, progress_callback=None, expected_commit: str | None = None,
                               expected_branch: str | None = None) -> IngestResult:
    """按 scan→parse→link→facts→projections→validate→publish 构建不可变快照。"""
    with _repo_lock(repo_id):
        record = get_repo_record(repo_id)
        if record is None:
            raise ValueError("没有找到指定仓库")
        repo_path = Path(record["repo_path"])
        ensure_clean_worktree(repo_path)
        commit_hash = get_current_commit(repo_path)
        if not commit_hash:
            raise RepositoryScanError("仓库还没有任何 commit，无法创建不可变快照。")
        branch = get_current_branch(repo_path)
        if expected_commit and commit_hash.lower() != expected_commit.strip().lower():
            raise RepositoryScanError("刷新提交在任务启动前已变化，请重新刷新。")
        if expected_branch is not None and branch != expected_branch:
            raise RepositoryScanError("刷新分支在任务启动前已变化，请重新刷新。")

        snapshot, created = get_or_create_snapshot(repo_id, commit_hash, branch)
        snapshot_id = snapshot["id"]
        if snapshot["status"] == "succeeded":
            set_active_snapshot(repo_id, snapshot_id)
            return IngestResult(repo_id, snapshot_id, commit_hash, "succeeded",
                                len(list_indexable_file_records(repo_id, snapshot_id)),
                                count_chunks(repo_id, snapshot_id), True)
        if snapshot["status"] == "cancelled":
            raise RuntimeError("该提交快照已取消，不能直接重用")
        if snapshot["status"] == "failed":
            _clear_failed_snapshot(repo_id, snapshot_id)
            if not retry_failed_snapshot(repo_id, snapshot_id, branch):
                raise RuntimeError("失败快照重试获取失败")
        elif not created:
            raise RuntimeError("该仓库提交的快照正在由另一个任务构建")

        callback = progress_callback or (lambda _progress, _message=None: None)
        try:
            callback(0.05, "扫描并捕获仓库文件")
            scanned_files = scan_repository_files(repo_path)
            captured = {item["relative_path"]: item.pop("captured_bytes")
                        for item in scanned_files if "captured_bytes" in item}
            ensure_clean_worktree(repo_path)
            if get_current_commit(repo_path) != commit_hash:
                raise RepositoryScanError("索引期间 Git HEAD 已变化，请重新刷新。")
            replace_file_records(repo_id, scanned_files, snapshot_id=snapshot_id)
            files = list_indexable_file_records(repo_id, snapshot_id)
            documents = _capture_documents(repo_id, snapshot_id, files, captured)

            callback(0.20, f"统一解析 {len(documents)} 个文件")
            results = [_normalize_parse_result(item) for item in default_registry().parse_all(documents)]
            _update_parse_statuses(repo_id, snapshot_id, results)
            failed = [item.document.path for item in results if item.status == "failed"]
            if failed:
                raise RuntimeError(f"解析器内部失败，拒绝发布：{', '.join(failed[:5])}")

            evidence = [fact for result in results for fact in result.evidence]
            symbols = [fact for result in results for fact in result.symbols]
            relations = [fact for result in results for fact in result.relations]
            diagnostics = [fact for result in results for fact in result.diagnostics]
            replace_all_snapshot_parse_results(repo_id, snapshot_id, evidence, symbols, relations, diagnostics)
            callback(0.55, "规范解析事实已保存")

            chunk_count = project_evidence_to_chunks(repo_id, snapshot_id)
            embedding_result = embed_snapshot_evidence(
                repo_id,
                snapshot_id,
                [
                    {
                        "id": item.id,
                        "content": item.content,
                        "content_hash": hashlib.sha256(item.content.encode("utf-8")).hexdigest(),
                    }
                    for item in evidence
                ],
            )
            if embedding_result.warning:
                callback(0.75, f"向量阶段 {embedding_result.status}: {embedding_result.warning}")
            else:
                callback(0.75, f"向量阶段完成：新增 {embedding_result.stored}，复用 {embedding_result.reused}")

            project_symbols_to_code_graph(repo_id, snapshot_id)
            catalog_items = build_catalog(
                record,
                {"id": snapshot_id, "repo_id": repo_id, "commit_hash": commit_hash, "branch": branch},
                files,
                list_evidence_units(repo_id, snapshot_id=snapshot_id, limit=10000),
                list_symbols(repo_id, snapshot_id=snapshot_id, limit=None),
                enhance=False,
            )
            replace_snapshot_catalog(repo_id, snapshot_id, catalog_items)
            callback(0.90, f"规则 Catalog 已生成 {len(catalog_items)} 张卡片")
            _validate_snapshot(repo_id, snapshot_id, len(scanned_files), chunk_count)
            callback(0.95, "代码图谱投影和完整性校验完成")

            ensure_clean_worktree(repo_path)
            if get_current_commit(repo_path) != commit_hash:
                raise RepositoryScanError("发布前 Git HEAD 已变化，本次快照不会切换 active。")
            if not publish_snapshot(repo_id, snapshot_id, branch, len(scanned_files)):
                raise RuntimeError("快照发布失败或状态已变化")
            try:
                callback(1.0, "快照索引完成并已切换 active")
            except Exception:
                # 发布已完成，通知失败不能反向把不可变快照标记为 failed。
                pass
            return IngestResult(
                repo_id, snapshot_id, commit_hash, "succeeded", len(files), chunk_count,
                embedding_status=embedding_result.status,
                embedding_warning=embedding_result.warning,
            )
        except Exception as exc:
            # CAS 失败保护：若 publish 已成功，不能再把快照降级为 failed。
            current = get_or_create_snapshot(repo_id, commit_hash, branch)[0]
            if current["status"] != "succeeded":
                fail_snapshot(snapshot_id, str(exc))
            raise
