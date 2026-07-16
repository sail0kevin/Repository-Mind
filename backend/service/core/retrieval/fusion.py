"""RRF 融合器：确定性合并多路候选并按证据 ID 去重。"""
from __future__ import annotations

from collections import defaultdict


class ReciprocalRankFusion:
    """使用 Reciprocal Rank Fusion，不引入首版禁止的 LLM reranker。"""

    def __init__(self, k: int = 60) -> None:
        self.k = max(1, int(k))

    @staticmethod
    def identity(item: dict) -> str:
        """优先用 chunk/evidence ID；兼容 fake retriever 的路径行范围。"""
        return str(
            item.get("chunk_id")
            or item.get("id")
            or "|".join(
                str(item.get(key) or "")
                for key in ("file_path", "start_line", "end_line", "content")
            )
        )

    def fuse(self, ranked_lists: list[list[dict]]) -> list[dict]:
        scores: dict[str, float] = defaultdict(float)
        selected: dict[str, dict] = {}
        source_ranks: dict[str, dict[str, int]] = defaultdict(dict)

        for channel_index, items in enumerate(ranked_lists):
            for fallback_rank, raw in enumerate(items, start=1):
                item = dict(raw)
                identity = self.identity(item)
                if not identity:
                    continue
                rank = max(1, int(item.get("rank") or fallback_rank))
                channel = str(item.get("retriever") or f"channel_{channel_index}")
                scores[identity] += 1.0 / (self.k + rank)
                source_ranks[identity][channel] = rank
                if identity not in selected:
                    selected[identity] = item
                else:
                    current = selected[identity]
                    current["signals"] = sorted(set(current.get("signals", [])) | set(item.get("signals", [])))
                    if not current.get("content") and item.get("content"):
                        current["content"] = item["content"]

        fused: list[dict] = []
        for identity, item in selected.items():
            item["score"] = scores[identity]
            item["rrf_score"] = scores[identity]
            item["source_ranks"] = dict(sorted(source_ranks[identity].items()))
            signals = set(item.get("signals", [])) | set(source_ranks[identity])
            item["signals"] = sorted(signals)
            reasons = []
            if "lexical" in signals:
                reasons.append("文本匹配")
            if "semantic" in signals:
                reasons.append("语义匹配")
            item["reason"] = " + ".join(reasons) or item.get("reason") or "检索匹配"
            fused.append(item)

        fused.sort(
            key=lambda item: (
                -float(item.get("score", 0.0)),
                str(item.get("file_path") or ""),
                int(item.get("start_line") or 0),
                self.identity(item),
            )
        )
        return fused
