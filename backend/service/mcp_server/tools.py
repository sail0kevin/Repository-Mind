"""
这个文件负责 MCP 的只读工具实现。
每个工具只做参数校验、调用现成核心模块、把结果套进统一 envelope，不重新实现扫描/检索/关系分析逻辑。
"""
from __future__ import annotations

import logging
import re
from time import perf_counter

from service.core.agent.models import AgentContext
from service.core.agent.tools import _rank_target_symbols, dependency_impact, test_runtime
from service.core.evidence import EvidenceAssembler, EvidenceBudget
from service.core.repo_map import build_repo_map, build_repo_summary
from service.core.retrieval import HybridRetriever
from service.mcp_server.envelope import (
    clamp_limit,
    clamp_text,
    envelope,
    error_envelope,
    evidence_item,
)
from service.mcp_server.snapshot_guard import SnapshotGuardError, resolve_repo_and_snapshot
from service.storage.chunk_store import count_chunks
from service.storage.evidence_store import get_evidence_unit, list_evidence_units, list_relations, list_symbols
from service.storage.repository_store import list_file_records, list_repo_records
from service.storage.retrieval_metrics_store import record_retrieval_metric


_LOCATION_TERM_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_QUALIFIED_METHOD_RE = re.compile(r"\b([A-Z][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\b")
_QUALIFIED_SYMBOL_RE = re.compile(r"\b(?:[A-Za-z_][A-Za-z0-9_]*\.){2,}[A-Za-z_][A-Za-z0-9_]*\b")
_LOCATION_STOP_WORDS = {
    "a", "after", "an", "and", "another", "are", "as", "asks", "at", "be", "before", "by",
    "code", "decide", "does", "for", "from", "function", "functions", "generates", "how", "in",
    "into", "is", "it", "its", "locate", "location", "of", "on", "or", "proceeds", "report", "result",
    "results", "successful", "that", "the", "this", "to", "two", "waits", "when", "whether", "where", "with",
    "agent", "agents", "workflow", "workflows",
}
_SOURCE_SUFFIXES = {".c", ".cc", ".cpp", ".cs", ".go", ".java", ".js", ".jsx", ".py", ".rb", ".rs", ".ts", ".tsx"}
_LOCATION_QUERY_EXPANSIONS = {
    "handler": "adapter",
}


def _record_mcp_retrieval_metric(
    *,
    repo_id: str,
    snapshot_id: str,
    tool_name: str,
    query: str,
    retrievals: list,
    returned_count: int,
    started_at: float,
) -> None:
    """指标异常不能影响 MCP 的只读检索结果。"""
    try:
        primary = retrievals[0]
        scores = [
            run.run.relevance.observation.rrf_top_score
            for run in retrievals
            if run.run.relevance is not None
            and run.run.relevance.observation.rrf_top_score is not None
        ]
        record_retrieval_metric(
            repo_id=repo_id,
            snapshot_id=snapshot_id,
            tool_name=tool_name,
            retrieval_mode=primary.run.mode,
            query=query,
            returned_count=returned_count,
            top_score=max(scores, default=None),
            duration_ms=(perf_counter() - started_at) * 1000,
        )
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).warning("failed to record MCP retrieval metric", exc_info=True)


def _identifier_terms(value: str) -> set[str]:
    """Split normal words plus snake_case/camelCase identifiers into comparable terms."""
    terms: set[str] = set()
    for raw in _LOCATION_TERM_RE.findall(value):
        for part in re.split(r"_|(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", raw):
            if part:
                terms.add(part.casefold())
    return terms


def _location_terms(question: str) -> set[str]:
    """Keep meaningful English identifiers/words for narrow code-location windows."""
    terms = {
        term
        for term in _identifier_terms(question)
        if len(term) >= 3 and term.casefold() not in _LOCATION_STOP_WORDS
    }
    for source, target in _LOCATION_QUERY_EXPANSIONS.items():
        if source in terms:
            terms.add(target)
    return terms


def _explicit_class_names(question: str) -> set[str]:
    """Keep class-like identifiers exactly as written in a location question.

    A capitalized identifier alone is not proof that it names a class. It only
    becomes a ranking signal after it exactly matches a class component in a
    parsed qualified symbol, such as ``HTTPAdapter`` in
    ``requests.adapters.HTTPAdapter.send``.
    """
    return {
        raw.casefold()
        for raw in _LOCATION_TERM_RE.findall(question)
        if any(character.isupper() for character in raw)
    }


def _explicit_qualified_methods(question: str) -> set[tuple[str, str]]:
    """Extract only explicit ``Class.method`` clues from a natural-language question."""
    return {
        (class_name.casefold(), method_name.casefold())
        for class_name, method_name in _QUALIFIED_METHOD_RE.findall(question)
    }


def _explicit_qualified_symbols(question: str) -> set[str]:
    """Extract fully qualified symbol hints explicitly written by the caller.

    Parsers may add a repository namespace such as ``src.``. A user normally
    writes the import-facing name, so matching accepts only an exact qualified
    name or a dot-boundary suffix, never an arbitrary substring.
    """
    return {value.casefold() for value in _QUALIFIED_SYMBOL_RE.findall(question)}


def _location_queries(question: str) -> list[str]:
    """Keep the complete question and independently retrieve paired behavior clues.

    Location questions commonly ask for two connected code sites. A lexical index
    treats the complete sentence as an AND-heavy bag of words, which can hide both
    targets behind generic words such as ``request`` or ``session``. Splitting only
    explicit paired clauses retains the user's original wording without turning an
    arbitrary prompt into an unbounded list of keyword searches.
    """
    normalized = " ".join(question.split())
    clauses = [normalized]
    paired_parts = re.split(
        r"\s*,?\s+and\s+(?=(?:where|the|how|a|an)\b)", normalized, flags=re.IGNORECASE
    )
    if len(paired_parts) > 1:
        leading = paired_parts[0].strip(" ,.;")
        if len(_location_terms(leading)) >= 2 and leading not in clauses:
            clauses.append(leading)
    for part in paired_parts[1:]:
        part = part.strip(" ,.;")
        if len(_location_terms(part)) >= 3 and part not in clauses:
            clauses.append(part)
    expanded = []
    for clause in clauses:
        replacement = clause
        for source, target in _LOCATION_QUERY_EXPANSIONS.items():
            replacement = re.sub(rf"\b{source}\b", target, replacement, flags=re.IGNORECASE)
        if replacement != clause and replacement not in clauses and replacement not in expanded:
            expanded.append(replacement)
    return (clauses + expanded)[:4]


def _location_rank(location: dict) -> tuple[float, float, float, float, float, float, float, float, float, float, str, int]:
    """Prefer executable source evidence before equally relevant prose mentions."""
    coverage = len(set(location.get("matched_terms") or []))
    path = str(location["file_path"]).replace("\\", "/").casefold()
    source_rank = 2.0 if any(path.endswith(suffix) for suffix in _SOURCE_SUFFIXES) else 0.0
    if source_rank and any(part in path for part in ("/test", ".test.", ".spec.", "/e2e/")):
        source_rank = 1.0
    return (
        source_rank,
        float(location.get("explicit_qualified_symbol_match") or 0.0),
        float(location.get("explicit_qualified_method_match") or 0.0),
        float(location.get("explicit_class_match") or 0.0),
        float(location.get("exact_symbol_match") or 0.0),
        float(location.get("score") or 0.0),
        float(location.get("executable_matches") or 0.0),
        float(location.get("relation_corroboration") or 0.0),
        float(location.get("symbol_compactness") or 0.0),
        float(coverage),
        path,
        -int(location["start_line"]),
    )


def _location_symbol(location: dict) -> str | None:
    value = (
        location.get("qualified_name")
        or location.get("symbol_name")
        or location.get("name")
    )
    if value is None:
        return None
    normalized = " ".join(str(value).split())
    return normalized[:160] or None


def _location_kind(location: dict) -> str:
    value = location.get("symbol_kind") or location.get("kind") or location.get("chunk_type")
    value = str(value or "").casefold()
    return value if value in {"function", "method", "class", "module"} else "unknown"


def _compact_location_basis(location: dict) -> str:
    if any(
        float(location.get(key) or 0.0) > 0
        for key in (
            "explicit_qualified_symbol_match",
            "explicit_qualified_method_match",
            "explicit_class_match",
        )
    ) or float(location.get("exact_symbol_match") or 0.0) >= 2:
        return "exact_symbol"
    if float(location.get("executable_matches") or 0.0) > 0:
        return "body_match"
    if _location_symbol(location) is not None or _location_kind(location) != "unknown":
        return "symbol_match"
    return "retrieval"


def _structural_location(candidate: dict, terms: set[str], *, allow_class: bool = False) -> dict | None:
    """Keep a retrieved function, method, or class as one usable code location."""
    path = str(candidate.get("file_path") or candidate.get("path") or "").replace("\\", "/")
    start_line, end_line = candidate.get("start_line"), candidate.get("end_line")
    unit_type = str(candidate.get("chunk_type") or candidate.get("unit_type") or "")
    if (
        unit_type not in ({"function", "method", "class"} if allow_class else {"function", "method"})
        or not path
        or not isinstance(start_line, int)
        or not isinstance(end_line, int)
    ):
        return None
    lines = str(candidate.get("content") or "").splitlines()
    executable_matches = sum(_executable_match_count(lines, terms).values())
    return {
        "file_path": path,
        "start_line": start_line,
        "end_line": end_line,
        "evidence_id": candidate.get("chunk_id") or candidate.get("id") or "",
        "reason": "Retrieved parsed code definition for the complete question",
        "score": float(candidate.get("score") or 0.0),
        "matched_terms": sorted(_identifier_terms(str(candidate.get("content") or "")) & terms),
        "executable_matches": executable_matches,
        "symbol_name": candidate.get("symbol_name") or candidate.get("name"),
        "qualified_name": candidate.get("qualified_name"),
        "symbol_kind": candidate.get("symbol_kind") or (unit_type if unit_type in {"function", "method", "class"} else None),
    }


def _executable_match_count(lines: list[str], terms: set[str]) -> dict[int, int]:
    """Count term hits on executable lines while ignoring ordinary comments and docstrings."""
    counts: dict[int, int] = {}
    in_triple_quoted_string = False
    triple_quote = ""
    in_block_comment = False
    for offset, line in enumerate(lines):
        stripped = line.strip()
        is_non_code = not stripped or stripped.startswith(("#", "//", "*"))
        if in_triple_quoted_string:
            is_non_code = True
            if triple_quote in stripped:
                in_triple_quoted_string = False
                triple_quote = ""
        elif stripped.startswith(("'''", '\"\"\"')):
            is_non_code = True
            quote = stripped[:3]
            if stripped.count(quote) < 2:
                in_triple_quoted_string = True
                triple_quote = quote
        elif stripped.startswith("/*"):
            is_non_code = True
            in_block_comment = "*/" not in stripped[2:]
        elif in_block_comment:
            is_non_code = True
            if "*/" in stripped:
                in_block_comment = False
        if not is_non_code:
            counts[offset] = len(_identifier_terms(line) & terms)
    return counts


def _location_windows(candidate: dict, terms: set[str]) -> list[dict]:
    """Turn a broad retrieved block into small line windows around question terms."""
    content = str(candidate.get("content") or "")
    start_line = candidate.get("start_line")
    if not content or not isinstance(start_line, int) or not terms:
        return []

    lines = content.splitlines()
    executable_matches = _executable_match_count(lines, terms)
    scored_lines: list[tuple[int, int, int]] = []
    for offset, line in enumerate(lines):
        words = _identifier_terms(line)
        score = len(words & terms)
        if score:
            scored_lines.append((score, executable_matches.get(offset, 0), start_line + offset))
    if not scored_lines:
        return []

    end_line = candidate.get("end_line")
    span = end_line - start_line + 1 if isinstance(end_line, int) else 0
    unit_type = str(candidate.get("chunk_type") or candidate.get("unit_type") or "")
    candidate_score = float(candidate.get("score") or 0.0)
    # A small parsed function/class is already a meaningful source boundary. Returning
    # that boundary keeps its definition line, which a window centered on a later `if`
    # would otherwise hide from the caller.
    if unit_type in {"function", "method", "class"} and 0 < span <= 24:
        matched_terms = sorted({term for term in terms if term in _identifier_terms(content)})
        return [{
            "file_path": candidate.get("file_path") or candidate.get("path"),
            "start_line": start_line,
            "end_line": end_line,
            "evidence_id": candidate.get("chunk_id") or candidate.get("id") or "",
            "reason": "Matched question terms in a parsed code definition",
            "score": max(score for score, _, _ in scored_lines) * 100 + candidate_score,
            "matched_terms": matched_terms,
            "executable_matches": sum(executable_matches.values()),
            "symbol_name": candidate.get("symbol_name") or candidate.get("name"),
            "qualified_name": candidate.get("qualified_name"),
            "symbol_kind": candidate.get("symbol_kind") or (unit_type if unit_type in {"function", "method", "class"} else None),
        }]

    # A line usually needs its condition/body context. Keep the best distinct windows,
    # not a single large enclosing function that obscures several separate locations.
    windows: list[dict] = []
    for score, executable_count, line in sorted(scored_lines, key=lambda item: (-item[1], -item[0], item[2])):
        window_start = max(start_line, line - 6)
        window_end = min(start_line + len(content.splitlines()) - 1, line + 1)
        if any(
            window_start <= item["end_line"] and item["start_line"] <= window_end
            for item in windows
        ):
            continue
        windows.append({
            "file_path": candidate.get("file_path") or candidate.get("path"),
            "start_line": window_start,
            "end_line": window_end,
            "evidence_id": candidate.get("chunk_id") or candidate.get("id") or "",
            "reason": "Matched question terms near this source line",
            "score": score * 100 + candidate_score,
            "matched_terms": sorted(_identifier_terms("\n".join(content.splitlines()[
                max(0, window_start - start_line):window_end - start_line + 1
            ])) & terms),
            "executable_matches": executable_count,
            "symbol_name": candidate.get("symbol_name") or candidate.get("name"),
            "qualified_name": candidate.get("qualified_name"),
            "symbol_kind": candidate.get("symbol_kind") or (unit_type if unit_type in {"function", "method", "class"} else None),
        })
    return windows


def _symbol_locations_for_windows(repo_id: str, snapshot_id: str, windows: list[dict]) -> list[dict]:
    """Map text hits in a broad module block back to parsed function/class boundaries."""
    symbols_by_path: dict[str, list[dict]] = {}
    for symbol in list_symbols(repo_id, snapshot_id, limit=None):
        path = str(symbol.get("file_path") or "").replace("\\", "/")
        start_line, end_line = symbol.get("start_line"), symbol.get("end_line")
        if not path or not isinstance(start_line, int) or not isinstance(end_line, int):
            continue
        if str(symbol.get("symbol_kind") or "") not in {"function", "method", "class"}:
            continue
        symbols_by_path.setdefault(path, []).append(symbol)

    locations: list[dict] = []
    for window in windows:
        path = str(window.get("file_path") or "").replace("\\", "/")
        start_line, end_line = window.get("start_line"), window.get("end_line")
        if not path or not isinstance(start_line, int) or not isinstance(end_line, int):
            continue
        for symbol in symbols_by_path.get(path, []):
            symbol_start, symbol_end = symbol["start_line"], symbol["end_line"]
            if symbol_start > end_line or symbol_end < start_line:
                continue
            span = symbol_end - symbol_start + 1
            if span <= 24:
                location_start, location_end = symbol_start, symbol_end
                reason = "Parsed definition containing matched source lines"
            else:
                location_start, location_end = start_line, end_line
                reason = "Matched source lines inside a larger parsed definition"
            locations.append({
                "file_path": path,
                "start_line": location_start,
                "end_line": location_end,
                "evidence_id": symbol.get("evidence_id") or window.get("evidence_id") or "",
                "reason": reason,
                "score": float(window.get("score") or 0.0) + 50,
                "matched_terms": list(window.get("matched_terms") or []),
                "symbol_name": symbol.get("name"),
                "qualified_name": symbol.get("qualified_name"),
                "symbol_kind": symbol.get("symbol_kind"),
            })
    return locations


def _symbol_locations_for_terms(
    repo_id: str,
    snapshot_id: str,
    terms: set[str],
    *,
    minimum_matches: int = 1,
    explicit_class_names: set[str] | None = None,
    explicit_qualified_methods: set[tuple[str, str]] | None = None,
    explicit_qualified_symbols: set[str] | None = None,
) -> list[dict]:
    """Expose parsed definitions whose qualified names are explicit question clues."""
    explicit_class_names = explicit_class_names or set()
    explicit_qualified_methods = explicit_qualified_methods or set()
    explicit_qualified_symbols = explicit_qualified_symbols or set()
    infos: list[dict] = []
    for symbol in list_symbols(repo_id, snapshot_id, limit=None):
        kind = str(symbol.get("symbol_kind") or "")
        start_line, end_line = symbol.get("start_line"), symbol.get("end_line")
        path = str(symbol.get("file_path") or "").replace("\\", "/")
        name_terms = _identifier_terms(str(symbol.get("name") or ""))
        qualified_name = str(symbol.get("qualified_name") or "")
        normalized_qualified_name = qualified_name.casefold()
        qualified_terms = _identifier_terms(qualified_name)
        matched_terms = sorted((name_terms | qualified_terms) & terms)
        qualified_parts = [part.casefold() for part in qualified_name.split(".")]
        class_match = (
            kind == "method"
            and bool(set(qualified_parts[:-1]) & explicit_class_names)
        )
        qualified_method_match = (
            kind == "method"
            and len(qualified_parts) >= 2
            and (qualified_parts[-2], qualified_parts[-1]) in explicit_qualified_methods
        )
        qualified_symbol_match = any(
            normalized_qualified_name == hint or normalized_qualified_name.endswith(f".{hint}")
            for hint in explicit_qualified_symbols
        )
        if (
            kind not in {"function", "method", "class"}
            or not path
            or (len(matched_terms) < minimum_matches and not class_match and not qualified_symbol_match)
        ):
            continue
        if not isinstance(start_line, int) or not isinstance(end_line, int):
            continue
        qualified_bonus = len((qualified_terms & terms) - set(matched_terms))
        # A looser class-overlap check that works even when kind != "method": any
        # explicit class name from the question appears in the qualified path prefix.
        # Used by Fix A to preserve single-term matches for explicitly named classes.
        qualified_class_overlap = bool(set(qualified_parts[:-1]) & explicit_class_names)
        infos.append({
            "symbol_id": str(symbol.get("id") or ""),
            "path": path,
            "start_line": start_line,
            "end_line": end_line,
            "evidence_id": symbol.get("evidence_id") or "",
            "matched_terms": matched_terms,
            "exact_symbol_match": len(matched_terms) + qualified_bonus,
            "explicit_class_match": 1.0 if class_match else 0.0,
            "explicit_qualified_method_match": 1.0 if qualified_method_match else 0.0,
            "explicit_qualified_symbol_match": 1.0 if qualified_symbol_match else 0.0,
            "qualified_class_overlap": qualified_class_overlap,
            "symbol_name": symbol.get("name"),
            "qualified_name": qualified_name,
            "symbol_kind": kind,
        })

    # A symbol reached by a resolved, observed ``calls`` edge from a symbol that
    # already matches the question strongly (an "anchor") is corroborated by the
    # parsed call graph, not just word overlap. That structural signal should let
    # it survive the per-file cap even when a compact, equally lexical, but
    # unrelated same-name match would otherwise take the slot.
    anchor_ids = {info["symbol_id"] for info in infos if info["exact_symbol_match"] >= 2}
    corroborated_ids: set[str] = set()
    if anchor_ids:
        for relation in list_relations(repo_id, snapshot_id, limit=None):
            if (
                relation.get("relation_type") != "calls"
                or relation.get("resolver_status") != "resolved"
                or not relation.get("observed")
            ):
                continue
            source_id = str(relation.get("source_symbol_id") or "")
            target_id = str(relation.get("target_symbol_id") or "")
            if source_id in anchor_ids and target_id:
                corroborated_ids.add(target_id)
            if target_id in anchor_ids and source_id:
                corroborated_ids.add(source_id)

    locations: list[dict] = []
    for info in infos:
        relation_corroboration = 1.0 if info["symbol_id"] in corroborated_ids else 0.0
        evidence = get_evidence_unit(repo_id, str(info["evidence_id"] or ""), snapshot_id)
        # A two-term qualified match (for example, ``Response`` + ``status``)
        # is already precise enough to return the parser's full method boundary.
        # Do not let a small internal window outrank that boundary and force the
        # caller to fetch the surrounding branch or definition separately.
        window_added = False
        if evidence is not None and minimum_matches < 2:
            for window in _location_windows(evidence, terms):
                if not window.get("executable_matches"):
                    continue
                window.update({
                    "evidence_id": info["evidence_id"] or window.get("evidence_id") or "",
                    "reason": "Executable source lines inside a parsed definition match the question",
                    "exact_symbol_match": info["exact_symbol_match"],
                    "explicit_class_match": info["explicit_class_match"],
                    "explicit_qualified_method_match": info["explicit_qualified_method_match"],
                    "explicit_qualified_symbol_match": info["explicit_qualified_symbol_match"],
                    "relation_corroboration": relation_corroboration,
                    "symbol_compactness": 1.0 / max(1, info["end_line"] - info["start_line"] + 1),
                    "symbol_name": info["symbol_name"],
                    "qualified_name": info["qualified_name"],
                    "symbol_kind": info["symbol_kind"],
                })
                locations.append(window)
                window_added = True
        # Executable body lines matching query terms let this boundary entry outrank a
        # symbol that only matched via its qualified name (Fix B). Reuse the already-
        # fetched evidence; no extra DB round-trips needed.
        boundary_exec = 0
        if evidence is not None:
            ev_lines = str(evidence.get("content") or "").splitlines()
            boundary_exec = sum(_executable_match_count(ev_lines, terms).values())
        # Fix A: skip the full-boundary entry for weak single-term matches in the
        # fallback pass when the body has no real content evidence. A class-name-only
        # overlap on a trivial dunder or stub method would otherwise outrank legitimately
        # relevant methods via the symbol_compactness tie-breaker.
        # qualified_class_overlap keeps symbols whose class is *explicitly named* in the
        # query (e.g. "Session sends" → "Session" uppercase) even when kind != "method".
        if (
            minimum_matches >= 2
            or window_added
            or len(info["matched_terms"]) >= 2
            or info["explicit_class_match"]
            or info["explicit_qualified_method_match"]
            or info["explicit_qualified_symbol_match"]
            or info.get("qualified_class_overlap")
        ):
            locations.append({
                "file_path": info["path"],
                "start_line": info["start_line"],
                "end_line": info["end_line"],
                "evidence_id": info["evidence_id"],
                "reason": "Parsed definition whose symbol name matches the question",
                "score": 1000.0 if minimum_matches >= 2 else 0.0,
                "matched_terms": info["matched_terms"],
                "exact_symbol_match": info["exact_symbol_match"],
                "explicit_class_match": info["explicit_class_match"],
                "explicit_qualified_method_match": info["explicit_qualified_method_match"],
                "explicit_qualified_symbol_match": info["explicit_qualified_symbol_match"],
                "relation_corroboration": relation_corroboration,
                "symbol_compactness": 1.0 / max(1, info["end_line"] - info["start_line"] + 1),
                "executable_matches": boundary_exec,
                "symbol_name": info["symbol_name"],
                "qualified_name": info["qualified_name"],
                "symbol_kind": info["symbol_kind"],
            })
    return locations


def list_repositories(limit: int | None = None) -> dict:
    """列出可供 MCP 查询的仓库和活动快照，不暴露本机绝对路径。"""
    normalized_limit = clamp_limit(limit, default=100, maximum=100)
    try:
        records = list_repo_records(limit=normalized_limit)
    except Exception as exc:  # noqa: BLE001 - MCP 进程不能因单次调用异常崩溃
        return error_envelope("", f"列出仓库失败：{exc}")

    repositories = [
        {
            "repo_id": item["id"],
            "alias": item.get("alias"),
            "branch": item.get("branch"),
            "snapshot_id": item.get("active_snapshot_id"),
            "commit": item.get("active_commit_hash"),
            "snapshot_status": item.get("active_snapshot_status"),
            "file_count": item.get("file_count") or 0,
            "indexed": item.get("active_snapshot_status") == "succeeded",
        }
        for item in records
    ]
    indexed_count = sum(1 for item in repositories if item["indexed"])
    limitations = []
    if indexed_count < len(repositories):
        limitations.append("未完成索引的仓库仅用于状态提示；其他查询工具只能使用带 succeeded 活动快照的仓库。")
    return envelope(
        repo_id="",
        status="ok",
        data={
            "repositories": repositories,
            "total": len(repositories),
            "indexed_count": indexed_count,
        },
        limitations=limitations,
    )


def _guard_or_envelope(repo_id: str, snapshot_id: str | None):
    """公共前置校验；返回 (guard_result, None) 或 (None, 已构造好的错误 envelope)。"""
    guard = resolve_repo_and_snapshot(repo_id, snapshot_id)
    if isinstance(guard, SnapshotGuardError):
        return None, envelope(repo_id=repo_id, snapshot_id=snapshot_id, status=guard.status, limitations=[guard.message])
    return guard, None


def repo_overview(repo_id: str, snapshot_id: str | None = None) -> dict:
    """返回仓库别名、commit、快照 ID、文件统计和推荐阅读顺序，明确标注只读索引结果。"""
    guard, failure = _guard_or_envelope(repo_id, snapshot_id)
    if failure is not None:
        return failure
    try:
        files = list_file_records(repo_id, limit=5000, snapshot_id=guard.snapshot["id"])
        repo_map = build_repo_map(guard.repo, files, chunk_count=count_chunks(repo_id, guard.snapshot["id"]))
        summary = build_repo_summary(repo_map)
    except Exception as exc:  # noqa: BLE001 - MCP 进程不能因单次调用异常崩溃
        return error_envelope(repo_id, f"生成仓库概览失败：{exc}", snapshot_id=guard.snapshot["id"])

    return envelope(
        repo_id=repo_id,
        snapshot_id=guard.snapshot["id"],
        commit=guard.snapshot["commit_hash"],
        status="ok",
        data={
            "alias": repo_map["alias"],
            "status": repo_map["status"],
            "branch": repo_map["branch"],
            "file_count": repo_map["file_count"],
            "indexable_file_count": repo_map["indexable_file_count"],
            "chunk_count": repo_map["chunk_count"],
            "language_counts": repo_map["language_counts"],
            "category_counts": repo_map["category_counts"],
            "key_files": repo_map["key_files"],
            "recommended_reading_order": summary["recommended_reading_order"],
            "summary": summary["summary"],
            "next_steps": summary["next_steps"],
        },
        limitations=["这是只读索引结果，不代表当前工作区未提交的改动。"],
    )


def search_code(repo_id: str, query: str, snapshot_id: str | None = None, limit: int | None = None) -> dict:
    """混合检索代码证据；embedding 不可用时如实报告 lexical 降级，不返回整份文件。"""
    guard, failure = _guard_or_envelope(repo_id, snapshot_id)
    if failure is not None:
        return failure
    normalized_query = clamp_text(query)
    if not normalized_query:
        return error_envelope(repo_id, "query 不能为空。", status="error", snapshot_id=guard.snapshot["id"])
    normalized_limit = clamp_limit(limit, default=6, maximum=20)
    started_at = perf_counter()

    try:
        retrieval = HybridRetriever().retrieve(
            repo_id, guard.snapshot["id"], normalized_query, normalized_limit
        )
        bundle = EvidenceAssembler(EvidenceBudget(
            total_tokens=1200,
            max_file_ratio=0.5,
            max_evidence_tokens=320,
            min_sources=2,
            max_items=6,
        )).assemble(retrieval.items, commit=guard.snapshot["commit_hash"], limit=normalized_limit)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(repo_id, f"检索失败：{exc}", snapshot_id=guard.snapshot["id"])

    mode = retrieval.run.mode
    semantic_channel = retrieval.run.channels.get("semantic")
    degraded = mode != "hybrid" or semantic_channel == 0
    status = "degraded" if degraded else "ok"
    limitations = []
    if mode != "hybrid":
        limitations.append("语义向量检索当前不可用（未配置或该快照没有 embedding），本次结果只使用关键词（lexical）检索，可能遗漏语义相关但字面不匹配的代码。")
    elif semantic_channel == 0:
        limitations.append("本次语义检索没有返回任何结果（embedding provider 可能异常或返回了空向量），已回退为只展示关键词（lexical）检索命中的结果。")

    evidence = [
        evidence_item(
            {
                "chunk_id": item.chunk_id,
                "file_path": item.path,
                "start_line": item.start_line,
                "end_line": item.end_line,
                "content": item.content,
            },
            reason=item.reason,
        )
        for item in bundle.items
    ]
    _record_mcp_retrieval_metric(
        repo_id=repo_id,
        snapshot_id=guard.snapshot["id"],
        tool_name="search_code",
        query=normalized_query,
        retrievals=[retrieval],
        returned_count=len(evidence),
        started_at=started_at,
    )
    if not evidence:
        limitations.append(
            "当前 Snapshot 中没有检索到可返回的代码证据；请改用更具体的符号名、文件路径或配置键，"
            "也可先调用 get_symbol 确认符号是否存在。"
        )
        return envelope(
            repo_id=repo_id,
            snapshot_id=guard.snapshot["id"],
            commit=guard.snapshot["commit_hash"],
            status="not_found",
            data={
                "query": normalized_query,
                "retrieval_mode": mode,
                "evidence_budget": bundle.stats,
            },
            limitations=limitations,
        )
    return envelope(
        repo_id=repo_id,
        snapshot_id=guard.snapshot["id"],
        commit=guard.snapshot["commit_hash"],
        status=status,
        data={
            "query": normalized_query,
            "retrieval_mode": mode,
            "evidence_budget": bundle.stats,
        },
        evidence=evidence,
        limitations=limitations,
    )


_CONTEXT_INTENT_MARKERS = {
    "behavior": (
        "behavior",
        "flow",
        "works",
        "called",
        "invoked",
        "returns",
        "logic",
        "process",
        "how does",
        "what happens",
        "实现",
        "行为",
        "流程",
        "逻辑",
        "如何",
        "怎么",
        "调用",
        "返回",
    ),
    "impact": (
        "impact",
        "affected",
        "affects",
        "caller",
        "callers",
        "reference",
        "references",
        "depend",
        "depends",
        "dependency",
        "modify",
        "modifies",
        "change",
        "changes",
        "changing",
        "break",
        "breaks",
        "callers are affected",
        "depends on",
        "影响",
        "受影响",
        "修改",
        "变更",
        "改动",
        "依赖",
        "调用方",
        "引用",
        "哪些文件",
    ),
    "test": (
        "test",
        "tests",
        "testing",
        "coverage",
        "verify",
        "validation",
        "pytest",
        "unittest",
        "which tests",
        "测试",
        "测试用例",
        "验证",
        "覆盖",
        "单测",
        "单元测试",
    ),
}


_RESPONSE_SCHEMA_MARKERS = (
    "return json",
    "return only json",
    "return a json",
    "respond with json",
    "reply with json",
    "output json",
    "json only",
)


def _strip_response_schema(question: str) -> str:
    """去掉"响应格式要求"那部分句子，只留真正的信息需求。

    复杂问题常在结尾附一句输出契约，例如
    "Return JSON only with evidence, claims, affected_paths, test_paths, and summary."
    这句描述的是**返回结构**，不是要找的代码。但它把 affected / test 这类词带进了问题，
    会让意图识别误判成"影响面分析"和"测试查找"，进而让补充证据走错工具；它也会稀释
    词法检索的查询词。所以在识别意图和抽取关键短语之前，先剔除这类句子。
    """
    normalized = " ".join(str(question or "").split())
    if not normalized:
        return ""
    sentences = re.split(r"(?<=[.!?;])\s+", normalized)
    kept = [
        sentence
        for sentence in sentences
        if not any(marker in sentence.casefold() for marker in _RESPONSE_SCHEMA_MARKERS)
    ]
    # 万一整个问题都像格式要求，保留原文；宁可不剔除，也不能把问题清空。
    return " ".join(kept).strip() or normalized


def _question_terms(question: str) -> set[str]:
    """问题里可用于比对的实词，已剔除响应格式要求和停用词。"""
    return {
        term
        for term in _identifier_terms(_strip_response_schema(question))
        if len(term) >= 3 and term not in _LOCATION_STOP_WORDS
    }


def _keyphrase_queries(question: str, *, max_queries: int = 6) -> list[str]:
    """把问题切成连续实词短语，作为窄召回查询。

    一整句自然语言问题在词法索引里就是几十个词的词袋，真正指向代码的信号会被通用词
    淹没，目标文件可能一条候选都进不了。但同一个问题里的连续实词短语往往能精确命中
    ——"local development user"、"model provider address" 这种。

    这里按停用词边界切出连续实词段，并对每段额外产出"去掉左侧修饰词"的后缀短语：
    名词短语的中心词在右侧，逐个丢弃左侧修饰词就是从最具体逐步放宽。这是通用的关键
    短语近似规则，不针对任何具体问题。
    """
    words = _LOCATION_TERM_RE.findall(_strip_response_schema(question))
    runs: list[list[str]] = []
    current: list[str] = []
    for word in words:
        folded = word.casefold()
        if len(folded) < 3 or folded in _LOCATION_STOP_WORDS:
            if len(current) >= 2:
                runs.append(current)
            current = []
            continue
        current.append(word)
    if len(current) >= 2:
        runs.append(current)

    # 长段更具体，优先；段内再从完整短语逐步去掉左侧修饰词。
    runs.sort(key=len, reverse=True)
    queries: list[str] = []
    seen: set[str] = set()
    for run in runs:
        # range 到 len-1：单个词太泛，不单独作为查询。
        for start in range(len(run) - 1):
            phrase = " ".join(run[start:])
            folded = phrase.casefold()
            if folded in seen:
                continue
            seen.add(folded)
            queries.append(phrase)
            if len(queries) >= max_queries:
                return queries
    return queries


def _context_intents(question: str) -> set[str]:
    stripped = _strip_response_schema(question)
    normalized = " ".join(stripped.casefold().split())
    terms = _identifier_terms(stripped)
    intents: set[str] = set()
    for intent, markers in _CONTEXT_INTENT_MARKERS.items():
        for marker in markers:
            folded = marker.casefold()
            if re.fullmatch(r"[a-z0-9_]+", folded):
                if folded in terms:
                    intents.add(intent)
                    break
                continue
            if folded in normalized:
                intents.add(intent)
                break
    return intents


def _path_is_test(path: str) -> bool:
    normalized = str(path or "").replace("\\", "/").casefold()
    return (
        normalized.startswith("tests/")
        or "/tests/" in f"/{normalized}"
        or normalized.startswith("test_")
        or ".test." in normalized
        or ".spec." in normalized
    )


def _evidence_path(item: dict) -> str:
    return str(item.get("file_path") or item.get("path") or "").replace("\\", "/")


def _evidence_identity(item: dict) -> tuple[str, str, object, object]:
    """按"位置"而不是"记录 ID"标识证据。

    同一段源码区域可能来自多条记录（切片投影、结构化补充、检索候选），它们的
    chunk_id 各不相同但指向同一批行。如果把 ID 放进去重键，这些近似重复项会各占
    一个证据槽位，把其他文件的证据挤出预算。去重必须只看 (路径, 起始行, 结束行)。
    """
    return (
        "",
        _evidence_path(item),
        item.get("start_line"),
        item.get("end_line"),
    )


def _evidence_has_line_range(item: dict) -> bool:
    """证据必须带可核对的行范围。

    工具契约要求调用方"先核对返回的行再下结论"。缺行号的证据无法核对，却会占用
    有限的证据预算，把可核对的证据挤掉。这类项一律不进入最终证据集。
    """
    start, end = item.get("start_line"), item.get("end_line")
    if start is None or end is None:
        return False
    try:
        return int(start) >= 0 and int(end) >= 0
    except (TypeError, ValueError):
        return False


def _evidence_is_definition(item: dict) -> bool:
    # 必须同时读 context_role 和 role：内部证据行用 context_role，而经过
    # envelope.evidence_item() 之后该键被重命名为 role。_apply_context_supplement
    # 处理的正是 envelope 形态的数据，只读 context_role 会让定义保护槽位恒不生效。
    descriptor = " ".join(
        str(item.get(key) or "")
        for key in ("context_role", "role", "reason", "evidence_id", "title", "symbol_name")
    ).casefold()
    return any(token in descriptor for token in ("definition", "implementation", "target symbol", "symbol definition"))


def _evidence_is_impact(item: dict) -> bool:
    # 同上：envelope 转换后 context_role 变成 role，两个键都要读。
    descriptor = " ".join(
        str(item.get(key) or "")
        for key in ("context_role", "role", "reason", "evidence_id")
    ).casefold()
    return any(token in descriptor for token in ("impact", "caller", "callee", "reference"))


def _evidence_coverage(evidence: list[dict]) -> dict[str, int | bool]:
    paths = {_evidence_path(item) for item in evidence if _evidence_path(item)}
    return {
        "evidence_count": len(evidence),
        "file_count": len(paths),
        "test_file_count": sum(1 for path in paths if _path_is_test(path)),
        "definition_count": sum(1 for item in evidence if _evidence_is_definition(item)),
        "impact_evidence_count": sum(1 for item in evidence if _evidence_is_impact(item)),
    }


def _evidence_question_overlap(item: dict, question_terms: set[str]) -> int:
    """证据的路径/符号与问题实词的重叠词数，用作"是否切题"的可计算信号。"""
    if not question_terms:
        return 0
    descriptor = " ".join(
        str(item.get(key) or "") for key in ("file_path", "path", "symbol", "symbol_name", "title")
    )
    return len(question_terms & _identifier_terms(descriptor))


def _context_evidence_is_off_topic(evidence: list[dict], question_terms: set[str]) -> bool:
    """整批证据与问题没有任何词面交集时，视为跑题。

    词法检索用整句问题查询时，通用词会把真正的目标文件挤出候选，返回一批路径与问题
    毫无关系的证据。这种结果条数和文件数都"够"，却答不了问题，必须触发补充召回。
    """
    if not evidence or not question_terms:
        return False
    return not any(_evidence_question_overlap(item, question_terms) for item in evidence)


def _keyphrase_recall_evidence(
    repo_id: str,
    question: str,
    snapshot_id: str | None,
    *,
    per_query_limit: int = 4,
    max_items_per_query: int = 2,
) -> list[dict]:
    """用问题里的连续实词短语做几次窄召回，补回整句查询漏掉的证据。

    只读、有界：查询条数由 _keyphrase_queries 封顶，每条只取前几项带行号的证据。
    """
    recalled: list[dict] = []
    for phrase in _keyphrase_queries(question):
        try:
            found = search_code(repo_id, phrase, snapshot_id, per_query_limit)
        except Exception:  # noqa: BLE001 - 窄召回是补充手段，失败不能影响主结果
            continue
        kept = 0
        for item in found.get("evidence", []):
            if not isinstance(item, dict) or not _evidence_has_line_range(item):
                continue
            packaged = dict(item)
            packaged["context_role"] = "keyphrase_recall"
            packaged["reason"] = f"keyphrase_recall({phrase}): {item.get('reason') or 'lexical match'}"
            recalled.append(packaged)
            kept += 1
            if kept >= max_items_per_query:
                break
    return recalled


def _context_needs_supplement(primary: dict, intents: set[str], question: str = "") -> bool:
    """Treat shallow hits as incomplete evidence for non-location questions."""
    evidence = primary.get("evidence") or []
    if not evidence:
        return True
    # 计算一次词面交集，供后面所有检查复用，避免重复调用 _question_terms。
    qt = _question_terms(question)
    # 跑题判定先于意图判定：意图识别失败只说明"分不出类"，不代表证据够用。
    if _context_evidence_is_off_topic(evidence, qt):
        return True
    if not intents:
        return False
    paths = {_evidence_path(item) for item in evidence}
    paths.discard("")
    if len(evidence) < 2 or len(paths) < 2:
        return True
    if intents.intersection({"impact", "test"}) and len(evidence) < 3:
        return True
    if "behavior" in intents and not any(_evidence_is_definition(item) for item in evidence):
        return True
    if "impact" in intents and not any(_evidence_is_impact(item) for item in evidence):
        return True
    if "test" in intents:
        # 测试类问题需要同时找到：
        # (1) 相关的测试文件（与问题词面 overlap ≥ 1）
        # (2) 相关的实现文件（与问题词面 overlap ≥ 2）
        # overlap=1 可能只是文件名里偶然含有 "test" 等通用词，阈值略高避免误判。
        # 任一缺失则触发补全，让 find_related_tests / get_symbol 补齐另一侧。
        has_relevant_test = any(
            _path_is_test(_evidence_path(item))
            and _evidence_question_overlap(item, qt) >= 1
            for item in evidence
            if _evidence_path(item)
        )
        has_relevant_impl = any(
            not _path_is_test(_evidence_path(item))
            and _evidence_question_overlap(item, qt) >= 2
            for item in evidence
            if _evidence_path(item)
        )
        if not has_relevant_test or not has_relevant_impl:
            return True
    return False


def _merge_context_evidence(
    primary: list[dict],
    supplemental: list[dict],
    *,
    intents: set[str],
    max_items: int = 8,
    question_terms: set[str] | None = None,
) -> list[dict]:
    """Deduplicate evidence while reserving slots for intent-specific proof.

    keyphrase_recall 项（context_role='keyphrase_recall'）已经经过词法精确匹配，
    优先级高于普通 supplemental；零词面交集的 primary 项在槽位填满后才能进入。
    """
    qt = question_terms or set()

    # keyphrase 候选提前分拣出来——它们是靶向召回结果，不参与普通优先级逻辑。
    keyphrase = [
        item for item in supplemental
        if (item.get("context_role") or item.get("role") or "") == "keyphrase_recall"
    ]
    other_supplemental = [
        item for item in supplemental
        if (item.get("context_role") or item.get("role") or "") != "keyphrase_recall"
    ]

    ordered = other_supplemental + primary if intents.intersection({"impact", "test"}) else primary + other_supplemental

    # 缺行范围的证据无法核对，先剔除；但如果剔完就没有证据了，宁可退回原集合，
    # 也不能返回空证据。
    verifiable = [item for item in ordered if _evidence_has_line_range(item)]
    if verifiable:
        ordered = verifiable

    # keyphrase 放最前：不管顺序如何，先保证靶向召回进入候选池。
    full_ordered = [item for item in keyphrase if _evidence_has_line_range(item)] + ordered

    unique: list[dict] = []
    seen: set[tuple[str, str, object, object]] = set()
    for item in full_ordered:
        identity = _evidence_identity(item)
        if identity in seen or not identity[1]:
            continue
        seen.add(identity)
        unique.append(item)

    selected: list[dict] = []
    selected_ids: set[tuple[str, str, object, object]] = set()

    def reserve(predicate) -> None:
        for candidate in unique:
            identity = _evidence_identity(candidate)
            if identity in selected_ids or not predicate(candidate):
                continue
            selected.append(candidate)
            selected_ids.add(identity)
            return

    # keyphrase 项无条件保留：最多预留 2 个槽，避免无关 keyphrase 占满预算。
    keyphrase_count = 0
    for item in unique:
        if (item.get("context_role") or item.get("role") or "") == "keyphrase_recall":
            identity = _evidence_identity(item)
            if identity not in selected_ids:
                selected.append(item)
                selected_ids.add(identity)
                keyphrase_count += 1
                if keyphrase_count >= 2:
                    break

    if "impact" in intents:
        reserve(_evidence_is_impact)
    if "test" in intents:
        reserve(lambda item: _path_is_test(_evidence_path(item)))
        reserve(lambda item: not _path_is_test(_evidence_path(item)))
    if not intents.intersection({"impact", "test"}) and any(_evidence_is_definition(item) for item in unique):
        reserve(lambda item: _evidence_is_definition(item) and not _path_is_test(_evidence_path(item)))
    if "behavior" in intents and "impact" not in intents and "test" not in intents:
        reserve(lambda item: not _path_is_test(_evidence_path(item)))

    # 按词面交集降序填充剩余槽位：有交集的项排在零交集项前面。
    remaining = [item for item in unique if _evidence_identity(item) not in selected_ids]
    if qt:
        remaining.sort(key=lambda item: -_evidence_question_overlap(item, qt))
    for item in remaining:
        identity = _evidence_identity(item)
        if identity in selected_ids:
            continue
        selected.append(item)
        selected_ids.add(identity)
        if len(selected) >= max_items:
            break
    return selected[:max_items]


def _context_target_location(
    repo_id: str, question: str, snapshot_id: str | None, intents: set[str]
) -> dict | None:
    """Resolve one high-signal implementation symbol before structured follow-up."""
    located = locate_code(repo_id, question, snapshot_id, limit=4, compact=True)
    locations = located.get("locations", [])
    if not isinstance(locations, list) or not locations:
        return None

    question_terms = _location_terms(question) or _identifier_terms(question)

    def score(location: dict) -> tuple[int, int, int, int, int, int, str, int]:
        symbol = str(location.get("symbol") or "")
        path = str(location.get("path") or location.get("file_path") or "").replace("\\", "/")
        symbol_terms = _identifier_terms(symbol)
        path_terms = _identifier_terms(path)
        overlap = len(question_terms & (symbol_terms | path_terms))
        match_rank = {
            "exact_symbol": 3,
            "body_match": 2,
            "symbol_match": 1,
            "retrieval": 0,
        }.get(str(location.get("match_basis") or "retrieval"), 0)
        kind_rank = {
            "function": 3,
            "method": 3,
            "class": 2,
            "module": 1,
            "unknown": 0,
        }.get(str(location.get("kind") or "unknown"), 0)
        intent_rank = 0
        if "test" in intents and _path_is_test(path):
            intent_rank += 1
        if "impact" in intents and not _path_is_test(path):
            intent_rank += 1
        primary_rank = 1 if bool(location.get("is_primary")) else 0
        symbol_rank = 1 if symbol.strip() else 0
        return (
            symbol_rank,
            primary_rank,
            intent_rank,
            match_rank,
            kind_rank,
            overlap,
            0 if _path_is_test(path) else 1,
            -int(location.get("rank") or 0),
        )

    ranked = sorted(locations, key=score, reverse=True)
    return ranked[0] if ranked else None


def _context_target_symbol(
    repo_id: str, question: str, snapshot_id: str | None, intents: set[str]
) -> str | None:
    location = _context_target_location(repo_id, question, snapshot_id, intents)
    symbol = location.get("symbol") if isinstance(location, dict) else None
    if isinstance(symbol, str) and symbol.strip():
        return symbol.strip()
    return None


def _needs_symbol_definition(primary_evidence: list[dict], intents: set[str]) -> bool:
    if not primary_evidence:
        return True
    if "test" in intents:
        return not any(not _path_is_test(_evidence_path(item)) for item in primary_evidence)
    return not any(_evidence_is_definition(item) for item in primary_evidence)


def _context_next_steps(intents: set[str], evidence: list[dict]) -> list[str]:
    """Return a short, deterministic reading order for complex questions."""
    steps: list[str] = []
    if "impact" in intents:
        steps.append("Start with the caller evidence, then verify the related tests before editing.")
    elif "test" in intents:
        steps.append("Start with the related tests, then trace back to the implementation they exercise.")
    elif "behavior" in intents:
        steps.append("Start with the implementation definition evidence, then follow callees or references.")
    else:
        steps.append("Read the returned evidence in rank order and answer only from verified source.")

    if any(_path_is_test(_evidence_path(item)) for item in evidence) and "test" not in intents:
        steps.append("Keep test evidence separate from implementation evidence.")
    elif any(_evidence_is_impact(item) for item in evidence) and "impact" not in intents:
        steps.append("Use the impact evidence only as supporting context.")
    elif any(_evidence_is_definition(item) for item in evidence) and "behavior" not in intents:
        steps.append("Treat the definition evidence as the primary anchor.")
    return steps[:2]


def _supplement_context_evidence(
    repo_id: str,
    question: str,
    snapshot_id: str | None,
    intents: set[str],
    *,
    primary_evidence: list[dict] | None = None,
    target_symbol: str | None = None,
) -> tuple[list[dict], list[str], str | None]:
    """Use one or two bounded structured tools to fill the detected evidence gap."""
    try:
        symbol = target_symbol or _context_target_symbol(repo_id, question, snapshot_id, intents)
        if not symbol:
            return [], ["Evidence coverage was insufficient, but no parsed target symbol was resolved."], None

        evidence: list[dict] = []
        limitations = [
            "Primary retrieval had shallow evidence coverage; bounded structured follow-up was added.",
        ]
        primary_items = list(primary_evidence or [])
        plans: list[tuple[str, object]] = []
        if "impact" in intents:
            plans.append(("static_impact_evidence", analyze_impact))
            if "test" in intents:
                plans.append(("related_test", find_related_tests))
            elif _needs_symbol_definition(primary_items, intents):
                plans.append(("symbol_definition", get_symbol))
        elif "test" in intents:
            plans.append(("related_test", find_related_tests))
            # 只有在 primary 里没有与问题词面 overlap≥2 的实现文件时，才调用 get_symbol 补充定义。
            # 仅有噪音非测试文件（如 registry.ts）不算有效实现覆盖，应继续触发 get_symbol。
            qt_local = _question_terms(question)
            has_relevant_impl = any(
                not _path_is_test(_evidence_path(item))
                and _evidence_question_overlap(item, qt_local) >= 2
                for item in primary_items
                if _evidence_path(item)
            )
            if not has_relevant_impl:
                plans.append(("symbol_definition", get_symbol))
        else:
            plans.append(("symbol_behavior_evidence", get_symbol))

        for role, tool in plans[:2]:
            structured = tool(repo_id, symbol, snapshot_id)
            for item in structured.get("evidence", [])[:4]:
                packaged = dict(item)
                packaged["context_role"] = role
                packaged["reason"] = f"{role}: {item.get('reason') or 'structured read-only analysis'}"
                evidence.append(packaged)
            limitations.extend(str(item) for item in structured.get("limitations", [])[:2])
        return evidence, limitations, symbol
    except Exception as exc:  # noqa: BLE001 - supplemental evidence must not hide primary results
        return [], [f"Structured evidence supplement failed: {exc}"], None


def _apply_context_supplement(primary: dict, repo_id: str, question: str, snapshot_id: str | None) -> dict:
    intents = _context_intents(question)
    if not _context_needs_supplement(primary, intents, question):
        return primary

    supplemental, supplement_limits, symbol = _supplement_context_evidence(
        repo_id,
        question,
        snapshot_id,
        intents,
        primary_evidence=list(primary.get("evidence") or []),
    )

    # 关键短语召回：当整句查询因词汇饱和返回跑题结果时，用问题里的连续实词短语做
    # 几次窄召回，把整句漏掉的证据（如同文件的兄弟函数定义）补进来。这是靶向召回，
    # 已经过短语词法精确匹配，不做路径词重叠过滤。
    keyphrase_ev = _keyphrase_recall_evidence(repo_id, question, snapshot_id)

    data = primary.get("data")
    if isinstance(data, dict):
        primary_evidence = list(primary.get("evidence") or [])
        qt = _question_terms(question)

        # 普通 supplemental 走路径词重叠过滤（keyphrase 已靶向，不过滤）。
        if qt:
            relevant_supplemental = [
                item
                for item in supplemental
                if qt & _identifier_terms(item.get("file_path") or item.get("path") or "")
            ]
        else:
            relevant_supplemental = supplemental

        merged = _merge_context_evidence(
            primary_evidence,
            keyphrase_ev + relevant_supplemental,
            intents=intents,
            max_items=8,
            question_terms=qt,
        )
        primary["evidence"] = merged
        data["query"] = question
        data["context_intent"] = sorted(intents)
        data["target_symbol"] = symbol
        data["evidence_coverage"] = {
            **_evidence_coverage(merged),
            "supplemented": bool(supplemental),
        }
        data["recommended_follow_up"] = _context_next_steps(intents, merged)
    primary.setdefault("limitations", []).extend(supplement_limits)
    return primary


def _recover_context_from_structure(
    repo_id: str,
    question: str,
    snapshot_id: str | None,
    limit: int | None,
    intents: set[str],
) -> dict | None:
    guard, failure = _guard_or_envelope(repo_id, snapshot_id)
    if failure is not None:
        return failure

    symbol = _context_target_symbol(repo_id, question, snapshot_id, intents)
    if not symbol:
        return None

    symbol_recovery = search_code(repo_id, symbol, snapshot_id, limit)
    if symbol_recovery.get("evidence"):
        data = symbol_recovery.get("data")
        if isinstance(data, dict):
            data["query"] = question
            data["retrieval_query"] = symbol
            data["context_recovery"] = "symbol_search"
        limitations = symbol_recovery.get("limitations")
        if isinstance(limitations, list):
            limitations.append(
                "The original natural-language query returned no direct evidence; a bounded symbol recovery query was used."
            )
        recovered = _apply_context_supplement(symbol_recovery, repo_id, question, snapshot_id)
        recovered_data = recovered.get("data")
        if isinstance(recovered_data, dict):
            recovered_data["recommended_follow_up"] = _context_next_steps(
                intents, list(recovered.get("evidence") or [])
            )
        return recovered

    supplemental, supplement_limits, recovered_symbol = _supplement_context_evidence(
        repo_id,
        question,
        snapshot_id,
        intents,
        primary_evidence=[],
        target_symbol=symbol,
    )
    if not supplemental:
        return None

    normalized_limit = clamp_limit(limit, default=6, maximum=20)
    bundle = EvidenceAssembler(EvidenceBudget(
        total_tokens=1200,
        max_file_ratio=0.5,
        max_evidence_tokens=320,
        min_sources=2,
        max_items=6,
    )).assemble(supplemental, commit=guard.snapshot["commit_hash"], limit=normalized_limit)
    evidence = [
        evidence_item(
            {
                "chunk_id": item.chunk_id,
                "file_path": item.path,
                "start_line": item.start_line,
                "end_line": item.end_line,
                "content": item.content,
            },
            reason=item.reason,
        )
        for item in bundle.items
    ]
    if not evidence:
        return None

    limitations = [
        "The original natural-language query returned no direct evidence; this result uses bounded structural recovery from parsed symbols.",
    ]
    limitations.extend(supplement_limits[:3])
    return envelope(
        repo_id=repo_id,
        snapshot_id=guard.snapshot["id"],
        commit=guard.snapshot["commit_hash"],
        status="degraded",
        data={
            "query": question,
            "retrieval_query": recovered_symbol or symbol,
            "retrieval_mode": "structured_recovery",
            "evidence_budget": bundle.stats,
            "context_intent": sorted(intents),
            "target_symbol": recovered_symbol or symbol,
            "context_recovery": "structured_lookup",
            "evidence_coverage": {
                **_evidence_coverage(evidence),
                "supplemented": True,
            },
            "recommended_follow_up": _context_next_steps(intents, evidence),
        },
        evidence=evidence,
        limitations=limitations,
    )


def get_code_context(
    repo_id: str,
    question: str,
    snapshot_id: str | None = None,
    limit: int | None = None,
) -> dict:
    """Return budgeted source evidence with bounded lexical fallback for a complex question.

    The original natural-language question is always attempted first. Only when it
    yields no evidence do we retry up to two narrower identifier queries. The
    response preserves the original question and reports the fallback query so an
    agent can distinguish verified evidence from the recovery mechanism.
    """
    normalized_question = clamp_text(question)
    primary = search_code(repo_id, normalized_question, snapshot_id, limit)
    if primary.get("status") != "not_found":
        return _apply_context_supplement(primary, repo_id, normalized_question, snapshot_id)

    for retry_query in _location_retry_queries(normalized_question, [normalized_question]):
        recovered = search_code(repo_id, retry_query, snapshot_id, limit)
        if not recovered.get("evidence"):
            continue
        data = recovered.get("data")
        if isinstance(data, dict):
            data["query"] = normalized_question
            data["retrieval_query"] = retry_query
        limitations = recovered.get("limitations")
        if isinstance(limitations, list):
            limitations.append(
                "The original natural-language query returned no evidence; this result uses a bounded identifier fallback."
            )
        return _apply_context_supplement(recovered, repo_id, normalized_question, snapshot_id)

    intents = _context_intents(normalized_question)
    recovered = _recover_context_from_structure(repo_id, normalized_question, snapshot_id, limit, intents)
    if recovered is not None:
        return recovered

    return primary


def locate_code(
    repo_id: str,
    question: str,
    snapshot_id: str | None = None,
    limit: int | None = None,
    compact: bool = False,
) -> dict:
    """Return independent candidate locations for a natural-language code question.

    ``compact`` is intended for coding agents that only need answer-ready line
    locations.  It deliberately omits the echoed question, evidence identifiers,
    explanation text, and normal-success limitations so one location lookup does
    not consume context needed to reason about the returned source.
    """
    guard, failure = _guard_or_envelope(repo_id, snapshot_id)
    if failure is not None:
        return failure
    normalized_question = clamp_text(question)
    if not normalized_question:
        return error_envelope(repo_id, "question cannot be empty.", snapshot_id=guard.snapshot["id"])
    normalized_limit = clamp_limit(limit, default=6, maximum=12)
    started_at = perf_counter()

    try:
        retriever = HybridRetriever()
        retrieval_queries = _location_queries(normalized_question)
        retrieval = retriever.retrieve(
            repo_id, guard.snapshot["id"], retrieval_queries[0], max(normalized_limit * 2, 12)
        )
        retrievals = [retrieval]
        candidate_by_id: dict[str, dict] = {}
        for query_index, query in enumerate(retrieval_queries):
            result = retrieval if query_index == 0 else retriever.retrieve(
                repo_id, guard.snapshot["id"], query, max(normalized_limit, 6)
            )
            if query_index != 0:
                retrievals.append(result)
            for candidate in result.items:
                identity = str(candidate.get("chunk_id") or candidate.get("id") or "")
                if not identity:
                    continue
                current = candidate_by_id.get(identity)
                if current is None:
                    candidate_by_id[identity] = dict(candidate)
                else:
                    current["score"] = max(
                        float(current.get("score") or 0.0), float(candidate.get("score") or 0.0)
                    )
        retry_threshold = max(2, min(normalized_limit, 3))
        if (
            len(retrieval_queries) == 1
            and len(candidate_by_id) < retry_threshold
            and len(_location_terms(normalized_question)) >= 2
        ):
            for retry_query in _location_retry_queries(normalized_question, retrieval_queries):
                retry_result = retriever.retrieve(
                    repo_id, guard.snapshot["id"], retry_query, max(normalized_limit * 2, 12)
                )
                retrievals.append(retry_result)
                for candidate in retry_result.items:
                    identity = str(candidate.get("chunk_id") or candidate.get("id") or "")
                    if not identity:
                        continue
                    current = candidate_by_id.get(identity)
                    if current is None:
                        candidate_by_id[identity] = dict(candidate)
                    else:
                        current["score"] = max(
                            float(current.get("score") or 0.0), float(candidate.get("score") or 0.0)
                        )
        primary_candidates = list(candidate_by_id.values())
    except Exception as exc:  # noqa: BLE001
        return error_envelope(repo_id, f"Code location failed: {exc}", snapshot_id=guard.snapshot["id"])

    terms = _location_terms(normalized_question)
    explicit_class_names = _explicit_class_names(normalized_question)
    explicit_qualified_methods = _explicit_qualified_methods(normalized_question)
    explicit_qualified_symbols = _explicit_qualified_symbols(normalized_question)
    locations: list[dict] = []
    seen: set[tuple[str, int, int]] = set()
    for candidate in primary_candidates:
        location = _structural_location(candidate, terms)
        if location is None:
            continue
        identity = (location["file_path"], location["start_line"], location["end_line"])
        if identity not in seen:
            seen.add(identity)
            locations.append(location)

    # A qualified symbol is strong structural evidence when the question names at
    # least two of its class/module/method terms (for example, ``Response`` and
    # ``status``). Keep these hints even if broad lexical retrieval already returned
    # many weak candidates; otherwise a common-word query can hide the exact method.
    for location in _symbol_locations_for_terms(
        repo_id,
        guard.snapshot["id"],
        terms,
        minimum_matches=2,
        explicit_class_names=explicit_class_names,
        explicit_qualified_methods=explicit_qualified_methods,
        explicit_qualified_symbols=explicit_qualified_symbols,
    ):
        identity = (str(location["file_path"]), int(location["start_line"]), int(location["end_line"]))
        if identity in seen:
            # The lexical pass can already contain this exact method. Preserve the
            # stronger symbol evidence instead of treating it as a duplicate and
            # leaving the weak lexical score in place.
            for index, existing in enumerate(locations):
                existing_identity = (
                    str(existing["file_path"]), int(existing["start_line"]), int(existing["end_line"])
                )
                if existing_identity == identity:
                    locations[index] = location
                    break
        else:
            seen.add(identity)
            locations.append(location)

    # Behavior questions often describe a top-level helper without naming its
    # symbol. Keep weak symbol matches only when their parsed body contains the
    # question terms; this lets a public wrapper and its downstream method coexist
    # without treating every one-word symbol overlap as a result.
    for location in _symbol_locations_for_terms(
        repo_id,
        guard.snapshot["id"],
        terms,
        explicit_class_names=explicit_class_names,
        explicit_qualified_methods=explicit_qualified_methods,
        explicit_qualified_symbols=explicit_qualified_symbols,
    ):
        identity = (str(location["file_path"]), int(location["start_line"]), int(location["end_line"]))
        if identity not in seen:
            seen.add(identity)
            locations.append(location)

    # Classes are much broader than methods and commonly match incidental words in
    # a behavior question. They remain a fallback for class-only repositories.
    if not locations:
        for candidate in primary_candidates:
            location = _structural_location(candidate, terms, allow_class=True)
            if location is None:
                continue
            identity = (location["file_path"], location["start_line"], location["end_line"])
            if identity not in seen:
                seen.add(identity)
                locations.append(location)

    # Full-question retrieval is the normal path. Only use word-level recall when it
    # did not yield enough parsed source definitions; otherwise words such as
    # "request" and "session" overwhelm a behavioral question with unrelated hits.
    if len(locations) < 2:
        candidate_by_id = {
            str(candidate.get("chunk_id") or candidate.get("id") or ""): candidate
            for candidate in primary_candidates
            if str(candidate.get("chunk_id") or candidate.get("id") or "")
        }
        try:
            for term in sorted(terms, key=lambda value: (-len(value), value))[:12]:
                term_result = retriever.retrieve(repo_id, guard.snapshot["id"], term, 8)
                retrievals.append(term_result)
                for candidate in term_result.items:
                    identity = str(candidate.get("chunk_id") or candidate.get("id") or "")
                    if identity:
                        candidate_by_id.setdefault(identity, dict(candidate))
        except Exception as exc:  # noqa: BLE001
            return error_envelope(repo_id, f"Code location failed: {exc}", snapshot_id=guard.snapshot["id"])
        candidates = list(candidate_by_id.values())
        windows = [
            location
            for candidate in candidates
            for location in _location_windows(candidate, terms)
        ]
        for location in windows:
            path = str(location.get("file_path") or "").replace("\\", "/")
            start_line, end_line = location.get("start_line"), location.get("end_line")
            if not path or not isinstance(start_line, int) or not isinstance(end_line, int):
                continue
            identity = (path, start_line, end_line)
            if identity not in seen:
                seen.add(identity)
                locations.append(location)
        for location in _symbol_locations_for_windows(repo_id, guard.snapshot["id"], windows):
            identity = (str(location["file_path"]), int(location["start_line"]), int(location["end_line"]))
            if identity not in seen:
                seen.add(identity)
                locations.append(location)
        for location in _symbol_locations_for_terms(
            repo_id,
            guard.snapshot["id"],
            terms,
            explicit_class_names=explicit_class_names,
            explicit_qualified_methods=explicit_qualified_methods,
            explicit_qualified_symbols=explicit_qualified_symbols,
        ):
            identity = (str(location["file_path"]), int(location["start_line"]), int(location["end_line"]))
            if identity not in seen:
                seen.add(identity)
                locations.append(location)
    else:
        candidates = primary_candidates

    # Some source formats do not expose useful line-level terms. Preserve the retrieved
    # structural boundary as a clearly marked fallback instead of inventing a precise line.
    if not locations:
        for candidate in candidates:
            path = str(candidate.get("file_path") or candidate.get("path") or "").replace("\\", "/")
            start_line, end_line = candidate.get("start_line"), candidate.get("end_line")
            if not path or not isinstance(start_line, int) or not isinstance(end_line, int):
                continue
            identity = (path, start_line, end_line)
            if identity in seen:
                continue
            seen.add(identity)
            locations.append({
                "file_path": path,
                "start_line": start_line,
                "end_line": end_line,
                "evidence_id": candidate.get("chunk_id") or candidate.get("id") or "",
                "reason": "Retrieved structural boundary; verify the exact statement before citing it",
                "score": float(candidate.get("score") or 0.0),
                "symbol_name": candidate.get("symbol_name") or candidate.get("name"),
                "qualified_name": candidate.get("qualified_name"),
                "symbol_kind": candidate.get("symbol_kind") or (str(candidate.get("chunk_type") or "") if str(candidate.get("chunk_type") or "") in {"function", "method", "class"} else None),
            })

    locations.sort(key=_location_rank, reverse=True)
    # Evidence is often projected into overlapping module, export, and function
    # chunks. Keep the strongest window for one source region, so callers spend
    # their limited context on separate locations rather than duplicate snippets.
    compact_locations: list[dict] = []
    for location in locations:
        path = str(location["file_path"]).replace("\\", "/")
        start_line, end_line = int(location["start_line"]), int(location["end_line"])
        if any(
            path == str(existing["file_path"]).replace("\\", "/")
            and start_line <= int(existing["end_line"])
            and int(existing["start_line"]) <= end_line
            for existing in compact_locations
        ):
            continue
        compact_locations.append(location)
    locations = compact_locations
    # Return a small, diverse set. The top-ranked file may hold three locations
    # when limit >= 6 — compound queries often target multiple sites within one
    # large module (e.g. sessions.py).  All other files stay capped at two so
    # diverse cross-file evidence is preserved.
    leading_file: str | None = None
    selected: list[dict] = []
    selected_per_file: dict[str, int] = {}
    for item in locations:
        path = str(item["file_path"]).replace("\\", "/")
        if leading_file is None:
            leading_file = path
        cap = 3 if (path == leading_file and normalized_limit >= 6) else 2
        if selected_per_file.get(path, 0) >= cap:
            continue
        selected.append(item)
        selected_per_file[path] = selected_per_file.get(path, 0) + 1
        if len(selected) >= normalized_limit:
            break
    mode = retrieval.run.mode
    status = "ok" if mode == "hybrid" else "degraded"
    limitations = [
        "Candidate locations are retrieval evidence, not proof of behavior. Verify the returned line before making a factual claim.",
        "Each location is independent. Report relevant locations separately instead of merging them into one broad range.",
    ]
    if mode != "hybrid":
        limitations.insert(0, "Semantic retrieval is unavailable for this snapshot; locations use lexical retrieval only.")
    _record_mcp_retrieval_metric(
        repo_id=repo_id,
        snapshot_id=guard.snapshot["id"],
        tool_name="locate_code",
        query=normalized_question,
        retrievals=retrievals,
        returned_count=len(selected),
        started_at=started_at,
    )
    if not selected:
        if compact:
            return {
                "repo_id": repo_id,
                "snapshot_id": guard.snapshot["id"],
                "commit": guard.snapshot["commit_hash"],
                "status": "not_found",
                "retrieval_mode": mode,
                "locations": [],
                "limitations": limitations,
            }
        return envelope(
            repo_id=repo_id,
            snapshot_id=guard.snapshot["id"],
            commit=guard.snapshot["commit_hash"],
            status="not_found",
            data={"question": normalized_question, "retrieval_mode": mode, "locations": []},
            limitations=limitations,
        )
    if compact:
        result = {
            "repo_id": repo_id,
            "snapshot_id": guard.snapshot["id"],
            "commit": guard.snapshot["commit_hash"],
            "status": status,
            "locations": [
                {
                    "path": item["file_path"],
                    "start_line": item["start_line"],
                    "end_line": item["end_line"],
                    "rank": rank,
                    "is_primary": rank == 1,
                    "symbol": _location_symbol(item),
                    "kind": _location_kind(item),
                    "match_basis": _compact_location_basis(item),
                }
                for rank, item in enumerate(selected, start=1)
            ],
        }
        # A degraded result changes the meaning of the candidate ranking, so it
        # remains explicit even in the context-minimal representation.
        if status == "degraded":
            result["retrieval_mode"] = mode
            result["limitations"] = limitations
        return result
    return envelope(
        repo_id=repo_id,
        snapshot_id=guard.snapshot["id"],
        commit=guard.snapshot["commit_hash"],
        status=status,
        data={
            "question": normalized_question,
            "retrieval_mode": mode,
            "locations": [
                {
                    "file_path": item["file_path"],
                    "start_line": item["start_line"],
                    "end_line": item["end_line"],
                    "evidence_id": item["evidence_id"],
                    "reason": item["reason"],
                }
                for item in selected
            ],
        },
        limitations=limitations,
    )


def get_symbol(repo_id: str, symbol_query: str, snapshot_id: str | None = None) -> dict:
    """按名称/限定名查询符号；同名符号存在时返回候选列表并说明匹配方式。"""
    guard, failure = _guard_or_envelope(repo_id, snapshot_id)
    if failure is not None:
        return failure
    normalized_query = clamp_text(symbol_query)
    if not normalized_query:
        return error_envelope(repo_id, "symbol_query 不能为空。", snapshot_id=guard.snapshot["id"])

    try:
        symbols = list_symbols(repo_id, guard.snapshot["id"], query=normalized_query, limit=20)
        ranked = _rank_target_symbols(symbols, normalized_query)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(repo_id, f"符号查询失败：{exc}", snapshot_id=guard.snapshot["id"])

    if not ranked:
        return envelope(
            repo_id=repo_id, snapshot_id=guard.snapshot["id"], commit=guard.snapshot["commit_hash"],
            status="not_found", data={"query": normalized_query},
            limitations=[f"未在当前 Snapshot 中找到匹配符号 {normalized_query}。"],
        )

    target = ranked[0]
    try:
        relations = list_relations(repo_id, guard.snapshot["id"], limit=10000)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(repo_id, f"关系查询失败：{exc}", snapshot_id=guard.snapshot["id"])
    related = [
        item for item in relations
        if item.get("source_symbol_id") == target.get("id") or item.get("target_symbol_id") == target.get("id")
    ]

    evidence = []
    if target.get("evidence_id"):
        definition = get_evidence_unit(repo_id, target["evidence_id"], guard.snapshot["id"])
        evidence.append(evidence_item(
            definition or {
                "chunk_id": target.get("evidence_id"),
                "file_path": target.get("file_path"),
                "start_line": target.get("start_line"),
                "end_line": target.get("end_line"),
            },
            reason="符号定义",
        ))

    symbol_by_id = {
        item.get("id"): item
        for item in list_symbols(repo_id, guard.snapshot["id"], limit=None)
    }

    def compact_symbol(symbol_id: str | None) -> dict:
        symbol = symbol_by_id.get(symbol_id)
        if not symbol:
            return {"symbol_id": symbol_id}
        return {
            "name": symbol.get("name"),
            "qualified_name": symbol.get("qualified_name"),
            "file_path": symbol.get("file_path"),
            "start_line": symbol.get("start_line"),
        }

    candidates = [
        {
            "symbol_id": item.get("id"),
            "name": item.get("name"),
            "qualified_name": item.get("qualified_name"),
            "symbol_kind": item.get("symbol_kind"),
            "file_path": item.get("file_path"),
            "start_line": item.get("start_line"),
            "end_line": item.get("end_line"),
        }
        for item in ranked[:5]
    ]
    static_call_candidates = []
    for relation in related:
        if relation.get("relation_type") != "calls" or relation.get("source_symbol_id") != target.get("id"):
            continue
        if relation.get("resolver_status") != "resolved" or not relation.get("target_symbol_id"):
            continue
        called_symbol = symbol_by_id.get(relation["target_symbol_id"])
        if not called_symbol:
            continue
        static_call_candidates.append({
            **compact_symbol(relation["target_symbol_id"]),
            "relation_type": "calls",
            "resolution": "static",
        })
        called_evidence = get_evidence_unit(
            repo_id, called_symbol.get("evidence_id") or "", guard.snapshot["id"]
        )
        if called_evidence:
            evidence.append(evidence_item(called_evidence, reason="静态解析到的调用目标"))
    match_method = (
        "精确限定名匹配" if str(target.get("qualified_name") or "").casefold() == normalized_query.casefold()
        else "限定名后缀匹配" if str(target.get("qualified_name") or "").casefold().endswith(f".{normalized_query.casefold()}")
        else "短名称匹配"
    )
    limitations = []
    if len(ranked) > 1:
        limitations.append(f"找到 {len(ranked)} 个同名/相似符号，已按 {match_method} 排序，仅返回前 5 个候选；如需进一步区分，请提供限定名或路径。")

    return envelope(
        repo_id=repo_id,
        snapshot_id=guard.snapshot["id"],
        commit=guard.snapshot["commit_hash"],
        status="ok",
        data={
            "query": normalized_query,
            "match_method": match_method,
            "symbol": {
                "name": target.get("name"),
                "qualified_name": target.get("qualified_name"),
                "symbol_kind": target.get("symbol_kind"),
                "file_path": target.get("file_path"),
                "start_line": target.get("start_line"),
                "end_line": target.get("end_line"),
            },
            "relation_count": len(related),
            "relations": [
                {
                    "type": item.get("relation_type"),
                    "source": compact_symbol(item.get("source_symbol_id")),
                    "target": compact_symbol(item.get("target_symbol_id")),
                    "observed": bool(item.get("observed")),
                    "resolver_status": item.get("resolver_status"),
                }
                for item in related[:10]
            ],
            "static_call_candidates": static_call_candidates,
            "candidates": candidates,
            "candidate_count": len(ranked),
        },
        evidence=evidence,
        limitations=limitations,
    )


def analyze_impact(repo_id: str, symbol_query: str, snapshot_id: str | None = None) -> dict:
    """静态影响分析；明确区分已解析调用关系与仅有源码支撑的引用候选。"""
    guard, failure = _guard_or_envelope(repo_id, snapshot_id)
    if failure is not None:
        return failure
    normalized_query = clamp_text(symbol_query)
    if not normalized_query:
        return error_envelope(repo_id, "symbol_query 不能为空。", snapshot_id=guard.snapshot["id"])

    try:
        context = AgentContext(
            repo_id=repo_id,
            snapshot_id=guard.snapshot["id"],
            commit=guard.snapshot["commit_hash"],
            question=normalized_query,
            limit=30,
        )
        result = dependency_impact(context)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(repo_id, f"影响分析失败：{exc}", snapshot_id=guard.snapshot["id"])

    resolved_evidence = []
    reference_evidence = []
    definition_evidence = []
    for item in result.evidence:
        reason = str(item.get("reason") or "")
        packaged = evidence_item(
            {
                "chunk_id": item.get("chunk_id") or item.get("id"),
                "file_path": item.get("file_path"),
                "start_line": item.get("start_line"),
                "end_line": item.get("end_line"),
                "content": item.get("content"),
            },
            reason=reason,
        )
        if reason == "目标符号定义":
            definition_evidence.append(packaged)
        elif reason.startswith("源码引用候选"):
            reference_evidence.append(packaged)
        else:
            resolved_evidence.append(packaged)

    target = result.metadata.get("target")
    status = "ok" if target else "not_found"
    limitations = [result.limitation] if result.limitation else []
    limitations.append("静态分析无法覆盖动态调用、反射或无法确定类型的实例调用；引用候选仅表示源码中出现了同名调用，未必是真实调用边。")
    all_impact_evidence = definition_evidence + resolved_evidence + reference_evidence
    evidence_groups = {
        "definition": [item["evidence_id"] for item in definition_evidence],
        "resolved_callers": [item["evidence_id"] for item in resolved_evidence],
        "reference_candidates": [item["evidence_id"] for item in reference_evidence],
    }

    return envelope(
        repo_id=repo_id,
        snapshot_id=guard.snapshot["id"],
        commit=guard.snapshot["commit_hash"],
        status=status,
        data={
            "query": result.metadata.get("query"),
            "target_symbol": {
                "name": target.get("name"),
                "qualified_name": target.get("qualified_name"),
                "file_path": target.get("file_path"),
                "start_line": target.get("start_line"),
                "end_line": target.get("end_line"),
            } if target else None,
            "resolved_relations": [
                {
                    "relation_type": item.get("relation_type"),
                    "source_symbol_id": item.get("source_symbol_id"),
                    "target_symbol_id": item.get("target_symbol_id"),
                }
                for item in result.metadata.get("resolved_relations", [])[:10]
            ],
            "evidence_groups": evidence_groups,
            "evidence_count": len(all_impact_evidence),
            "summary": result.summary,
        },
        evidence=all_impact_evidence,
        limitations=limitations,
    )


def find_related_tests(repo_id: str, symbol_query: str | None = None, snapshot_id: str | None = None) -> dict:
    """定位测试/构建/入口文件候选；只做定位，绝不执行目标仓库代码。"""
    guard, failure = _guard_or_envelope(repo_id, snapshot_id)
    if failure is not None:
        return failure
    normalized_query = clamp_text(symbol_query) if symbol_query else ""

    try:
        context = AgentContext(
            repo_id=repo_id,
            snapshot_id=guard.snapshot["id"],
            commit=guard.snapshot["commit_hash"],
            question=normalized_query or "test",
            limit=30,
        )
        base_result = test_runtime(context)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(repo_id, f"测试定位失败：{exc}", snapshot_id=guard.snapshot["id"])

    limitations = ["本工具只定位测试/构建/入口文件，不会执行目标仓库的任何代码或测试。"]
    if not normalized_query:
        limitations.append("未提供 symbol_query，本次返回的是全部测试/构建/入口文件候选，没有做针对性筛选。")
        evidence = [
            evidence_item({"chunk_id": "", "file_path": item, "start_line": None, "end_line": None},
                          reason="测试/运行文件")
            for item in [file.get("relative_path") for file in base_result.metadata.get("files", [])]
        ]
        return envelope(
            repo_id=repo_id, snapshot_id=guard.snapshot["id"], commit=guard.snapshot["commit_hash"],
            status="ok", data={"files": [file.get("relative_path") for file in base_result.metadata.get("files", [])]},
            evidence=evidence, limitations=limitations,
        )

    try:
        impact_context = AgentContext(
            repo_id=repo_id, snapshot_id=guard.snapshot["id"], commit=guard.snapshot["commit_hash"],
            question=normalized_query, limit=30,
        )
        impact_result = dependency_impact(impact_context)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(repo_id, f"关联测试定位失败：{exc}", snapshot_id=guard.snapshot["id"])

    test_paths = {file.get("relative_path") for file in base_result.metadata.get("files", [])}
    related_evidence = []
    for item in impact_result.evidence:
        path = str(item.get("file_path") or "").replace("\\", "/")
        if path not in test_paths and not any(token in path.casefold() for token in ("test", "spec")):
            continue
        related_evidence.append(evidence_item(
            {
                "chunk_id": item.get("chunk_id") or item.get("id"),
                "file_path": item.get("file_path"),
                "start_line": item.get("start_line"),
                "end_line": item.get("end_line"),
                "content": item.get("content"),
            },
            reason=str(item.get("reason") or ""),
        ))

    if not related_evidence:
        limitations.append(f"没有找到与 {normalized_query} 直接关联的测试文件引用证据，以下仍给出全部测试文件候选供人工核实。")

    return envelope(
        repo_id=repo_id, snapshot_id=guard.snapshot["id"], commit=guard.snapshot["commit_hash"],
        status="ok",
        data={
            "symbol_query": normalized_query,
            "matched_test_files": sorted({item["file_path"] for item in related_evidence}),
            "all_test_files": sorted(test_paths),
        },
        evidence=related_evidence or [
            evidence_item({"chunk_id": "", "file_path": item, "start_line": None, "end_line": None},
                          reason="测试/运行文件（未确认与目标符号相关）")
            for item in sorted(test_paths)
        ],
        limitations=limitations,
    )
def _location_retry_queries(question: str, existing_queries: list[str]) -> list[str]:
    """Build a small fallback query set only for an underfilled initial recall.

    The original question remains the primary retrieval query. When it produces
    too few candidates, remove instruction words and retry with the meaningful
    terms in their original order. This recovers natural-language questions
    whose wording differs from source code without widening normal requests
    into unbounded word-by-word searches.
    """
    existing = {" ".join(query.split()).casefold() for query in existing_queries}
    ordered_terms: list[str] = []
    seen: set[str] = set()
    for raw in _LOCATION_TERM_RE.findall(question):
        for part in re.split(r"_|(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", raw):
            normalized = part.casefold()
            if (
                len(normalized) < 3
                or normalized in _LOCATION_STOP_WORDS
                or normalized in seen
            ):
                continue
            seen.add(normalized)
            ordered_terms.append(normalized)
    for source, target in _LOCATION_QUERY_EXPANSIONS.items():
        if source in seen and target not in seen:
            seen.add(target)
            ordered_terms.append(target)

    retries: list[str] = []
    if len(ordered_terms) >= 2:
        retries.append(" ".join(ordered_terms[:6]))
    if ordered_terms:
        # A leading identifier often names the target symbol when the complete
        # natural-language query has no lexical overlap with its implementation.
        retries.append(ordered_terms[0])
    return [query for query in retries if query.casefold() not in existing][:2]
