"""词法检索适配器：复用现有 chunk 搜索并规范化检索信号。"""
from __future__ import annotations

from collections.abc import Callable

from service.storage.chunk_store import search_chunks


class LexicalRetriever:
    """把存储层词法命中转换为 HybridRetriever 的统一候选。"""

    name = "lexical"

    def __init__(self, search: Callable[..., list[dict]] = search_chunks) -> None:
        self.search = search

    def retrieve(self, repo_id: str, snapshot_id: str, query: str, limit: int) -> list[dict]:
        rows = self.search(repo_id, query, limit=limit, snapshot_id=snapshot_id)
        results: list[dict] = []
        for rank, row in enumerate(rows, start=1):
            item = dict(row)
            item["chunk_id"] = item.get("chunk_id") or item.get("id")
            item["retriever"] = self.name
            item["rank"] = rank
            item["signals"] = sorted(set(item.get("signals", [])) | {"lexical"})
            item["reason"] = item.get("reason") or "文本匹配"
            results.append(item)
        return results
