"""结构扩展器：仅沿数据库中 observed 且已解析的关系扩展一跳。"""
from __future__ import annotations

from collections.abc import Callable

from service.storage.evidence_store import get_evidence_unit, list_relations, list_symbols


class StructuralExpander:
    """为种子证据补充直接调用、继承、导入等可观察邻居。"""

    name = "structural"

    def __init__(
        self,
        relation_loader: Callable[..., list[dict]] = list_relations,
        symbol_loader: Callable[..., list[dict]] = list_symbols,
        evidence_loader: Callable[..., dict | None] = get_evidence_unit,
    ) -> None:
        self.relation_loader = relation_loader
        self.symbol_loader = symbol_loader
        self.evidence_loader = evidence_loader

    def expand(self, repo_id: str, snapshot_id: str, seeds: list[dict], limit: int) -> list[dict]:
        if not seeds or limit <= 0:
            return []
        seed_ids = {str(item.get("chunk_id") or item.get("id") or "") for item in seeds}
        symbols = self.symbol_loader(repo_id, snapshot_id=snapshot_id, limit=None)
        symbol_by_id = {str(item["id"]): item for item in symbols}
        symbols_by_evidence: dict[str, list[str]] = {}
        for symbol in symbols:
            evidence_id = symbol.get("evidence_id")
            if evidence_id:
                symbols_by_evidence.setdefault(str(evidence_id), []).append(str(symbol["id"]))

        relations = self.relation_loader(repo_id, snapshot_id=snapshot_id, limit=None)
        candidates: dict[str, dict] = {}
        for relation in relations:
            if not bool(relation.get("observed")) or relation.get("resolver_status") != "resolved":
                continue
            source_evidence = relation.get("source_evidence_id")
            target_evidence = relation.get("target_evidence_id")
            source_symbol = relation.get("source_symbol_id")
            target_symbol = relation.get("target_symbol_id")
            if not source_evidence and source_symbol in symbol_by_id:
                source_evidence = symbol_by_id[source_symbol].get("evidence_id")
            if not target_evidence and target_symbol in symbol_by_id:
                target_evidence = symbol_by_id[target_symbol].get("evidence_id")

            endpoints = ((source_evidence, target_evidence), (target_evidence, source_evidence))
            for seed_endpoint, neighbor_id in endpoints:
                if not seed_endpoint or str(seed_endpoint) not in seed_ids or not neighbor_id:
                    continue
                neighbor_key = str(neighbor_id)
                if neighbor_key in seed_ids or neighbor_key in candidates:
                    continue
                evidence = self.evidence_loader(repo_id, neighbor_key, snapshot_id=snapshot_id)
                if evidence is None:
                    continue
                item = dict(evidence)
                item["chunk_id"] = item.get("id")
                item["retriever"] = self.name
                item["rank"] = len(candidates) + 1
                item["score"] = 0.0
                item["signals"] = ["structural", f"relation:{relation.get('relation_type', 'related')}"]
                item["reason"] = f"一跳结构扩展：{relation.get('relation_type', 'related')}"
                item["relation_path"] = [
                    str(seed_endpoint), str(relation.get("id") or ""), neighbor_key
                ]
                candidates[neighbor_key] = item
                if len(candidates) >= limit:
                    break
            if len(candidates) >= limit:
                break

        return sorted(
            candidates.values(),
            key=lambda item: (
                str(item.get("file_path") or ""),
                int(item.get("start_line") or 0),
                str(item.get("chunk_id") or ""),
            ),
        )
