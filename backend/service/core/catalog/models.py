"""M3 Repository Catalog 的稳定领域模型。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

CatalogKind = Literal[
    "symbol", "file", "directory", "subsystem", "repository_overview", "reading_guide"
]
GenerationMethod = Literal["rule", "llm_enhanced"]


@dataclass(frozen=True)
class CatalogItem:
    """一张可持久化的 Catalog 卡片，所有结论都携带来源 Evidence ID。"""

    id: str
    repo_id: str
    snapshot_id: str
    kind: CatalogKind
    title: str
    path: str | None
    parent_id: str | None
    summary: str
    details: dict[str, Any] = field(default_factory=dict)
    source_evidence_ids: tuple[str, ...] = ()
    freshness: str = "current_snapshot"
    known_unknowns: tuple[str, ...] = ()
    generation_method: GenerationMethod = "rule"
    model: str | None = None
    prompt_version: str = "catalog-rule-v1"
    token_count: int = 0

    def with_enhancement(self, summary: str, model: str, token_count: int, prompt_version: str) -> "CatalogItem":
        """仅替换自然语言摘要，规则事实、层级和 Evidence 绑定保持不变。"""
        return CatalogItem(
            id=self.id, repo_id=self.repo_id, snapshot_id=self.snapshot_id, kind=self.kind,
            title=self.title, path=self.path, parent_id=self.parent_id, summary=summary,
            details=self.details, source_evidence_ids=self.source_evidence_ids,
            freshness=self.freshness, known_unknowns=self.known_unknowns,
            generation_method="llm_enhanced", model=model, prompt_version=prompt_version,
            token_count=max(0, token_count),
        )
