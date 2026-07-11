"""
这个文件负责并行解析文件与并行构建向量嵌入。
它在整个框架里扮演"索引加速层"的角色：用多线程把 I/O 密集型的文件解析和 embedding 计算拆开来跑。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable

from service.core.chunker import parse_text_file


def _thread_local_safe_parse(file_record: dict, progress_callback) -> tuple[str, list[dict]]:
    """在单个线程中解析一个文件，并回调一次进度。"""
    chunks = parse_text_file(file_record)
    if progress_callback is not None:
        progress_callback(0.1, f"已解析 {file_record.get('relative_path')}")
    return file_record.get("relative_path", ""), chunks


def parallel_parse_files(
    files: Iterable[dict],
    max_workers: int = 4,
    progress_callback=None,
) -> dict[str, list[dict]]:
    """并行把多个文件解析成知识片段。"""
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
