"""EvidenceAssembler：在预算内生成可直接传给问答层的 Evidence Bundle。"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from service.core.evidence.budget import EvidenceBudget, estimate_tokens


@dataclass(frozen=True)
class EvidenceBundleItem:
    """M3 证据条目的稳定字段。"""

    commit: str
    path: str
    start_line: int | None
    end_line: int | None
    content: str
    score: float
    signals: list[str]
    reason: str
    relation_path: list[str]
    token_count: int
    chunk_id: str = ""
    source_type: str = "unknown"
    title: str | None = None
    symbol_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceBundle:
    """证据集合和预算统计。"""

    items: list[EvidenceBundleItem]
    total_tokens: int
    source_count: int
    truncated_count: int
    dropped_count: int
    budget: EvidenceBudget

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "item_count": len(self.items),
            "total_tokens": self.total_tokens,
            "source_count": self.source_count,
            "truncated_count": self.truncated_count,
            "dropped_count": self.dropped_count,
            "budget": asdict(self.budget),
        }


class EvidenceAssembler:
    """执行总 token、单文件占比、单证据长度与多来源约束。"""

    def __init__(self, budget: EvidenceBudget | None = None) -> None:
        self.budget = budget or EvidenceBudget()

    @staticmethod
    def _truncate(content: str, max_tokens: int) -> tuple[str, int, bool]:
        if estimate_tokens(content) <= max_tokens:
            return content, estimate_tokens(content), False
        # 逐字符截断很慢且破坏代码；按行和空白块累加，更适合源码证据。
        blocks = content.splitlines(keepends=True) or [content]
        selected: list[str] = []
        used = 0
        for block in blocks:
            block_tokens = estimate_tokens(block)
            if used + block_tokens > max_tokens:
                remaining = max_tokens - used
                if remaining > 0:
                    words = block.split()
                    partial: list[str] = []
                    for word in words:
                        cost = estimate_tokens(word)
                        if used + cost > max_tokens:
                            break
                        partial.append(word)
                        used += cost
                    if partial:
                        selected.append(" ".join(partial))
                break
            selected.append(block)
            used += block_tokens
        text = "".join(selected).rstrip()
        if not text:
            text = content[: max(1, max_tokens)]
            used = min(max_tokens, estimate_tokens(text))
        return f"{text}\n…" if text != content else text, used, True

    @staticmethod
    def _normalize_candidate(candidate: dict) -> dict | None:
        """规范化候选路径，并让带正文的同位置候选可稳定参与去重。"""
        path = str(candidate.get("file_path") or candidate.get("path") or "").strip().replace("\\", "/")
        while "//" in path:
            path = path.replace("//", "/")
        if not path:
            return None
        normalized = dict(candidate)
        normalized["file_path"] = path
        normalized["content"] = str(candidate.get("content") or candidate.get("snippet") or "")
        return normalized

    @staticmethod
    def _candidate_identity(candidate: dict) -> tuple:
        chunk_id = str(candidate.get("chunk_id") or candidate.get("id") or "").strip()
        if chunk_id:
            return ("evidence", chunk_id)
        return (
            "location",
            candidate["file_path"].casefold(),
            candidate.get("start_line"),
            candidate.get("end_line"),
        )

    def assemble(self, candidates: list[dict], *, commit: str, limit: int | None = None) -> EvidenceBundle:
        max_items = min(self.budget.max_items, max(1, int(limit))) if limit is not None else self.budget.max_items
        deduplicated: dict[tuple, dict] = {}
        for raw_candidate in candidates:
            candidate = self._normalize_candidate(raw_candidate)
            if candidate is None:
                continue
            identity = self._candidate_identity(candidate)
            current = deduplicated.get(identity)
            if current is None or (
                not str(current.get("content") or "").strip()
                and str(candidate.get("content") or "").strip()
            ):
                deduplicated[identity] = candidate

        ordered = sorted(
            deduplicated.values(),
            key=lambda item: (
                -int(item.get("specialist_priority") or 0),
                -float(item.get("score", 0.0)),
                str(item.get("file_path") or ""),
                int(item.get("start_line") or 0),
                str(item.get("chunk_id") or item.get("id") or ""),
            ),
        )
        by_path: dict[str, list[dict]] = {}
        for item in ordered:
            path = str(item.get("file_path") or item.get("path") or "")
            by_path.setdefault(path, []).append(item)

        # 先从不同文件各选一条，尽可能满足多来源，再按全局分数补齐。
        preferred: list[dict] = []
        for path in sorted(
            by_path,
            key=lambda key: (
                -int(bool(by_path[key][0].get("specialist_priority"))),
                -int(by_path[key][0].get("specialist_priority") or 0),
                -float(by_path[key][0].get("score", 0.0)),
                key,
            ),
        ):
            if len(preferred) >= min(self.budget.min_sources, max_items):
                break
            preferred.append(by_path[path][0])
        preferred_ids = {id(item) for item in preferred}
        selection_order = preferred + [item for item in ordered if id(item) not in preferred_ids]

        items: list[EvidenceBundleItem] = []
        file_tokens: dict[str, int] = {}
        total_tokens = 0
        truncated_count = 0
        dropped_count = 0
        used_ids: set[str] = set()
        for candidate in selection_order:
            if len(items) >= max_items:
                dropped_count += 1
                continue
            chunk_id = str(candidate.get("chunk_id") or candidate.get("id") or "")
            if chunk_id and chunk_id in used_ids:
                dropped_count += 1
                continue
            path = str(candidate.get("file_path") or candidate.get("path") or "")
            remaining_total = self.budget.total_tokens - total_tokens
            remaining_file = self.budget.max_file_tokens - file_tokens.get(path, 0)
            allowance = min(self.budget.max_evidence_tokens, remaining_total, remaining_file)
            if allowance <= 0:
                dropped_count += 1
                continue
            content, token_count, truncated = self._truncate(str(candidate.get("content") or ""), allowance)
            if token_count <= 0:
                dropped_count += 1
                continue
            if truncated:
                truncated_count += 1
            signals = sorted({str(value) for value in candidate.get("signals", []) if value})
            relation_path = [str(value) for value in candidate.get("relation_path", []) if value]
            items.append(EvidenceBundleItem(
                commit=commit,
                path=path,
                start_line=candidate.get("start_line"),
                end_line=candidate.get("end_line"),
                content=content,
                score=float(candidate.get("score", 0.0)),
                signals=signals,
                reason=str(candidate.get("reason") or "检索匹配"),
                relation_path=relation_path,
                token_count=token_count,
                chunk_id=chunk_id,
                source_type=str(candidate.get("source_type") or candidate.get("unit_type") or "unknown"),
                title=candidate.get("title"),
                symbol_name=candidate.get("symbol_name"),
            ))
            used_ids.add(chunk_id)
            total_tokens += token_count
            file_tokens[path] = file_tokens.get(path, 0) + token_count

        return EvidenceBundle(
            items=items,
            total_tokens=total_tokens,
            source_count=len({item.path for item in items}),
            truncated_count=truncated_count,
            dropped_count=dropped_count,
            budget=self.budget,
        )
