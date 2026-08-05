"""
并行解析文件入口（遗留兼容层）。

.. deprecated::
    主 ingest 管线已统一到 ``ParserRegistry``（见 ``ingest_service.py``）。
    本模块保留作为兼容入口，内部已改为调用 ``default_registry()``，
    产出与主 ingest 一致的 Evidence 结构，不再使用旧 ``chunker.py`` 的
    40 行固定切片。外部新代码请直接使用 ``ParserRegistry``。
"""
from __future__ import annotations

from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed

from service.core.parsing import SourceDocument, default_registry


def _to_source_document(file_record: dict) -> SourceDocument | None:
    """把文件记录转换为 SourceDocument，读取失败时返回 None。"""
    from pathlib import Path

    absolute_path = file_record.get("absolute_path") or file_record.get("repo_path")
    if not absolute_path:
        return None
    path = Path(absolute_path)
    if not path.exists() or not path.is_file():
        return None
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    if not content:
        return None
    return SourceDocument(
        snapshot_id=file_record.get("snapshot_id", "legacy"),
        path=file_record.get("relative_path", ""),
        content=content,
        language=file_record.get("language"),
        repo_id=file_record.get("repo_id"),
        file_id=file_record.get("id"),
        metadata={"absolute_path": absolute_path, "is_test_file": bool(file_record.get("is_test_file"))},
    )


def _thread_local_safe_parse(file_record: dict, progress_callback) -> tuple[str, list[dict]]:
    """在单个线程中解析一个文件，并回调一次进度。"""
    document = _to_source_document(file_record)
    if document is None:
        return file_record.get("relative_path", ""), []
    # 使用统一的 ParserRegistry，产出与主 ingest 一致的 Evidence。
    result = default_registry().parse(document)
    chunks = [
        {
            "file_id": file_record.get("id"),
            "file_path": file_record.get("relative_path"),
            "chunk_type": evidence.kind,
            "title": evidence.title,
            "symbol_name": evidence.metadata.get("symbol_name"),
            "start_line": evidence.start_line,
            "end_line": evidence.end_line,
            "content": evidence.content,
            "content_hash": evidence.content_hash,
            "token_count": len(evidence.content.split()),
            "embedding_status": "pending",
            "source_type": file_record.get("file_type", "text"),
            "metadata_json": evidence.metadata,
            "parent_id": evidence.parent_id,
        }
        for evidence in result.evidence
    ]
    if progress_callback is not None:
        progress_callback(0.1, f"已解析 {file_record.get('relative_path')}")
    return file_record.get("relative_path", ""), chunks


def parallel_parse_files(
    files: Iterable[dict],
    max_workers: int = 4,
    progress_callback=None,
) -> dict[str, list[dict]]:
    """并行把多个文件解析成知识片段。

    内部已改为使用统一的 ``ParserRegistry``，产出与主 ingest 一致的
    Evidence 结构。不再依赖旧 ``chunker.py`` 的 40 行固定切片。
    """
    file_list = list(files)
    results: dict[str, list[dict]] = {}
    if not file_list:
        return results
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(_thread_local_safe_parse, item, progress_callback)
            for item in file_list
        ]
        for future in as_completed(futures):
            relative_path, chunks = future.result()
            results[relative_path] = chunks
    return results


def parallel_build_embeddings(chunks: list[str], max_workers: int = 4, progress_callback=None) -> list[dict]:
    """构造 embedding 结果的占位结构。当前版本保留接口，后续可替换为真实 embedding 调用。"""
    outputs: list[dict] = []
    for index, text in enumerate(chunks):
        outputs.append({"id": f"emb_{index}", "chunk_id": None, "embedding": None})
        if progress_callback is not None and index % 10 == 0:
            progress_callback(0.6, f"已处理 {index + 1}/{len(chunks)} 个片段")
    return outputs


def batch_insert_embeddings(repo_id: str, embeddings: list[dict]) -> int:
    """批量写入 embedding 结果。当前版本仅作为占位入口。"""
    from service.core.vector_store import replace_repo_vector_index

    return replace_repo_vector_index(repo_id, embeddings)
