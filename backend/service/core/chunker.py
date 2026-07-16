"""
这个文件负责把单个文本文件切成知识片段。
它在整个框架里扮演"文本切片层"的角色：把源码或文档拆成适合检索的小块，并为每块保留路径、行号等上下文。
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

# 单个 chunk 的最大字符数
MAX_CHUNK_SIZE = 1500


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()


def parse_text_file(file_record: dict) -> list[dict]:
    """把单个文本文件切成知识片段列表。"""
    absolute_path = file_record.get("absolute_path") or file_record.get("repo_path")
    if not absolute_path:
        return []
    path = Path(absolute_path)
    if not path.exists() or not path.is_file():
        return []
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    if not content:
        return []
    lines = content.splitlines()
    return [
        {
            "file_id": file_record.get("id"),
            "file_path": file_record.get("relative_path"),
            "chunk_type": "python" if (file_record.get("extension") or "").endswith("py") else "text",
            "title": file_record.get("relative_path"),
            "symbol_name": None,
            "start_line": index + 1,
            "end_line": min(index + 40, len(lines)),
            "content": "\n".join(lines[index : index + 40]),
            "content_hash": _sha1("\n".join(lines[index : index + 40])),
            "token_count": len("\n".join(lines[index : index + 40]).split()),
            "embedding_status": "pending",
            "source_type": file_record.get("file_type", "text"),
            "metadata_json": None,
            "parent_id": None,
        }
        for index in range(0, len(lines), 40)
    ]
