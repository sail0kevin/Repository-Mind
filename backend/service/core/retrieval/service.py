"""HybridRetriever 编排服务：执行计划、融合、去重和结构扩展，并记录审计信息。"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import uuid

from service.core.retrieval.fusion import ReciprocalRankFusion
from service.core.retrieval.lexical import LexicalRetriever
from service.core.retrieval.planner import RetrievalPlanner
from service.core.retrieval.semantic import SemanticRetriever
from service.core.retrieval.structural import StructuralExpander


@dataclass
class RetrievalRun:
    """一次检索的可审计记录；不保存用户密钥或模型私有推理。"""

    run_id: str
    repo_id: str
    snapshot_id: str
    query: str
    mode: str
    started_at: str
    completed_at: str | None = None
    channels: dict[str, int] = field(default_factory=dict)
    fused_count: int = 0
    expanded_count: int = 0
    returned_count: int = 0
    events: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RetrievalResult:
    """检索候选和审计运行记录。"""

    items: list[dict]
    run: RetrievalRun


class HybridRetriever:
    """lexical + 可选 semantic RRF，并沿 observed 关系扩展一跳。"""

    def __init__(
        self,
        *,
        planner: RetrievalPlanner | None = None,
        lexical: LexicalRetriever | None = None,
        semantic: SemanticRetriever | None = None,
        fusion: ReciprocalRankFusion | None = None,
        structural: StructuralExpander | None = None,
    ) -> None:
        self.planner = planner or RetrievalPlanner()
        self.lexical = lexical or LexicalRetriever()
        self.semantic = semantic or SemanticRetriever()
        self.fusion = fusion or ReciprocalRankFusion()
        self.structural = structural or StructuralExpander()

    def retrieve(self, repo_id: str, snapshot_id: str, query: str, limit: int) -> RetrievalResult:
        semantic_available = self.semantic.available(repo_id, snapshot_id)
        plan = self.planner.plan(query, limit, semantic_available=semantic_available)
        now = datetime.now(timezone.utc).isoformat()
        run = RetrievalRun(
            run_id=f"retrieval_{uuid.uuid4().hex}",
            repo_id=repo_id,
            snapshot_id=snapshot_id,
            query=plan.query,
            mode=plan.mode,
            started_at=now,
            events=[{"stage": "plan", **asdict(plan)}],
        )

        ranked_lists: list[list[dict]] = []
        lexical_hits = self.lexical.retrieve(repo_id, snapshot_id, plan.query, plan.candidate_limit)
        ranked_lists.append(lexical_hits)
        run.channels["lexical"] = len(lexical_hits)

        if plan.use_semantic:
            semantic_hits = self.semantic.retrieve(repo_id, snapshot_id, plan.query, plan.candidate_limit)
            ranked_lists.append(semantic_hits)
            run.channels["semantic"] = len(semantic_hits)

        fused = self.fusion.fuse(ranked_lists)
        run.fused_count = len(fused)
        seed_limit = min(len(fused), plan.limit)
        seeds = fused[:seed_limit]
        expanded = self.structural.expand(
            repo_id,
            snapshot_id,
            seeds,
            max(0, plan.candidate_limit - len(seeds)),
        ) if plan.expand_structural else []
        run.expanded_count = len(expanded)

        seen = {self.fusion.identity(item) for item in seeds}
        combined = list(seeds)
        base_score = min((float(item.get("score", 0.0)) for item in seeds), default=0.0)
        for offset, item in enumerate(expanded, start=1):
            identity = self.fusion.identity(item)
            if identity in seen:
                continue
            seen.add(identity)
            # 结构扩展必须排在直接命中之后，同时维持确定性次序。
            item["score"] = max(0.0, base_score * 0.5) / offset
            combined.append(item)

        run.returned_count = len(combined)
        run.events.extend([
            {"stage": "retrieve", "channels": dict(run.channels)},
            {"stage": "fuse", "count": run.fused_count, "algorithm": "rrf", "llm_reranker": False},
            {"stage": "structural_expand", "count": run.expanded_count, "max_hops": 1, "observed_only": True},
        ])
        run.completed_at = datetime.now(timezone.utc).isoformat()
        return RetrievalResult(items=combined, run=run)
