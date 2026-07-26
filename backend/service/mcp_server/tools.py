"""
这个文件负责 MCP 的只读工具实现。
每个工具只做参数校验、调用现成核心模块、把结果套进统一 envelope，不重新实现扫描/检索/关系分析逻辑。
"""
from __future__ import annotations

import re

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


_LOCATION_TERM_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_LOCATION_STOP_WORDS = {
    "a", "after", "an", "and", "another", "are", "as", "asks", "at", "be", "before", "by",
    "code", "decide", "does", "for", "from", "function", "functions", "generates", "how", "in",
    "into", "is", "it", "its", "locate", "location", "of", "on", "or", "proceeds", "report", "result",
    "results", "successful", "that", "the", "this", "to", "two", "waits", "when", "whether", "where", "with",
    "agent", "agents", "workflow", "workflows",
}
_SOURCE_SUFFIXES = {".c", ".cc", ".cpp", ".cs", ".go", ".java", ".js", ".jsx", ".py", ".rb", ".rs", ".ts", ".tsx"}


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
    return {
        term
        for term in _identifier_terms(question)
        if len(term) >= 3 and term.casefold() not in _LOCATION_STOP_WORDS
    }


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
    for part in re.split(r"\s*,?\s+and\s+(?=(?:where|the|how|a|an)\b)", normalized, flags=re.IGNORECASE):
        part = part.strip(" ,.;")
        if len(_location_terms(part)) >= 3 and part not in clauses:
            clauses.append(part)
    return clauses[:3]


def _location_rank(location: dict) -> tuple[float, float, float, float, float, float, str, int]:
    """Prefer executable source evidence before equally relevant prose mentions."""
    coverage = len(set(location.get("matched_terms") or []))
    path = str(location["file_path"]).replace("\\", "/").casefold()
    source_rank = 2.0 if any(path.endswith(suffix) for suffix in _SOURCE_SUFFIXES) else 0.0
    if source_rank and any(part in path for part in ("/test", ".test.", ".spec.", "/e2e/")):
        source_rank = 1.0
    return (
        source_rank,
        float(location.get("exact_symbol_match") or 0.0),
        float(location.get("score") or 0.0),
        float(location.get("executable_matches") or 0.0),
        float(location.get("symbol_compactness") or 0.0),
        float(coverage),
        path,
        -int(location["start_line"]),
    )


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
            })
    return locations


def _symbol_locations_for_terms(
    repo_id: str, snapshot_id: str, terms: set[str], *, minimum_matches: int = 1
) -> list[dict]:
    """Expose parsed definitions whose qualified names are explicit question clues."""
    locations: list[dict] = []
    for symbol in list_symbols(repo_id, snapshot_id, limit=None):
        kind = str(symbol.get("symbol_kind") or "")
        start_line, end_line = symbol.get("start_line"), symbol.get("end_line")
        path = str(symbol.get("file_path") or "").replace("\\", "/")
        name_terms = _identifier_terms(str(symbol.get("name") or ""))
        qualified_terms = _identifier_terms(str(symbol.get("qualified_name") or ""))
        matched_terms = sorted((name_terms | qualified_terms) & terms)
        if (
            kind not in {"function", "method", "class"}
            or not path
            or len(matched_terms) < minimum_matches
        ):
            continue
        if not isinstance(start_line, int) or not isinstance(end_line, int):
            continue
        qualified_bonus = len((qualified_terms & terms) - set(matched_terms))
        evidence = get_evidence_unit(repo_id, str(symbol.get("evidence_id") or ""), snapshot_id)
        # A two-term qualified match (for example, ``Response`` + ``status``)
        # is already precise enough to return the parser's full method boundary.
        # Do not let a small internal window outrank that boundary and force the
        # caller to fetch the surrounding branch or definition separately.
        if evidence is not None and minimum_matches < 2:
            for window in _location_windows(evidence, terms):
                if not window.get("executable_matches"):
                    continue
                window.update({
                    "evidence_id": symbol.get("evidence_id") or window.get("evidence_id") or "",
                    "reason": "Executable source lines inside a parsed definition match the question",
                    "exact_symbol_match": len(matched_terms) + qualified_bonus,
                    "symbol_compactness": 1.0 / max(1, end_line - start_line + 1),
                })
                locations.append(window)
        locations.append({
            "file_path": path,
            "start_line": start_line,
            "end_line": end_line,
            "evidence_id": symbol.get("evidence_id") or "",
            "reason": "Parsed definition whose symbol name matches the question",
            "score": 1000.0 if minimum_matches >= 2 else 0.0,
            "matched_terms": matched_terms,
            "exact_symbol_match": len(matched_terms) + qualified_bonus,
            "symbol_compactness": 1.0 / max(1, end_line - start_line + 1),
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


def locate_code(repo_id: str, question: str, snapshot_id: str | None = None, limit: int | None = None) -> dict:
    """Return compact, independent candidate locations for a natural-language code question."""
    guard, failure = _guard_or_envelope(repo_id, snapshot_id)
    if failure is not None:
        return failure
    normalized_question = clamp_text(question)
    if not normalized_question:
        return error_envelope(repo_id, "question cannot be empty.", snapshot_id=guard.snapshot["id"])
    normalized_limit = clamp_limit(limit, default=6, maximum=12)

    try:
        retriever = HybridRetriever()
        retrieval_queries = _location_queries(normalized_question)
        retrieval = retriever.retrieve(
            repo_id, guard.snapshot["id"], retrieval_queries[0], max(normalized_limit * 2, 12)
        )
        candidate_by_id: dict[str, dict] = {}
        for query_index, query in enumerate(retrieval_queries):
            result = retrieval if query_index == 0 else retriever.retrieve(
                repo_id, guard.snapshot["id"], query, max(normalized_limit, 6)
            )
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
        primary_candidates = list(candidate_by_id.values())
    except Exception as exc:  # noqa: BLE001
        return error_envelope(repo_id, f"Code location failed: {exc}", snapshot_id=guard.snapshot["id"])

    terms = _location_terms(normalized_question)
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
        repo_id, guard.snapshot["id"], terms, minimum_matches=2
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
        for location in _symbol_locations_for_terms(repo_id, guard.snapshot["id"], terms):
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
    # Return a small, diverse set. At most two locations from one file prevents a
    # large module from consuming the caller's context budget.
    selected: list[dict] = []
    selected_per_file: dict[str, int] = {}
    for item in locations:
        path = str(item["file_path"]).replace("\\", "/")
        if selected_per_file.get(path, 0) >= 2:
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
    if not selected:
        return envelope(
            repo_id=repo_id,
            snapshot_id=guard.snapshot["id"],
            commit=guard.snapshot["commit_hash"],
            status="not_found",
            data={"question": normalized_question, "retrieval_mode": mode, "locations": []},
            limitations=limitations,
        )
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
