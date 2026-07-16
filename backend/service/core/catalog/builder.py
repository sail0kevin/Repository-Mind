"""从 M2 Evidence/Symbol 事实构建完整、离线可用的 Repository Catalog。"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
from pathlib import PurePosixPath
from typing import Iterable

from service.core.catalog.models import CatalogItem
from service.core.catalog.summarizer import enhance_catalog_items

_ENTRY_NAMES = {"main.py", "app.py", "server.py", "manage.py", "index.js", "index.ts", "main.js", "main.ts", "cli.py", "__main__.py"}
_CONFIG_NAMES = {"pyproject.toml", "package.json", "tsconfig.json", "dockerfile", "docker-compose.yml", "docker-compose.yaml", "requirements.txt", "setup.cfg", "tox.ini", ".env.example"}


def _id(snapshot_id: str, kind: str, identity: str) -> str:
    digest = hashlib.sha256(f"{snapshot_id}\0{kind}\0{identity}".encode("utf-8")).hexdigest()[:24]
    return f"catalog_{kind}_{digest}"


def _evidence_ids(rows: Iterable[dict]) -> tuple[str, ...]:
    return tuple(sorted({str(row["id"]) for row in rows if row.get("id")}))


def _path_evidence(evidence: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in evidence:
        grouped[str(row.get("file_path") or "")].append(row)
    return grouped


def _directory(path: str) -> str:
    parent = str(PurePosixPath(path).parent)
    return "" if parent == "." else parent


def _is_entry(path: str, symbols: list[dict]) -> bool:
    name = PurePosixPath(path).name.lower()
    if name in _ENTRY_NAMES:
        return True
    return any(str(item.get("name", "")).lower() == "main" for item in symbols)


def _is_config(file: dict) -> bool:
    path = str(file.get("relative_path") or "")
    name = PurePosixPath(path).name.lower()
    return name in _CONFIG_NAMES or str(file.get("language") or "").lower() in {"json", "yaml", "toml"}


def build_rule_catalog(repo: dict, snapshot: dict, files: list[dict], evidence: list[dict], symbols: list[dict]) -> list[CatalogItem]:
    """按 Symbol→File→Directory/Subsystem→Overview→Guide 顺序生成确定性卡片。"""
    repo_id, snapshot_id = repo["id"], snapshot["id"]
    by_path = _path_evidence(evidence)
    symbols_by_path: dict[str, list[dict]] = defaultdict(list)
    for symbol in symbols:
        symbols_by_path[str(symbol.get("file_path") or "")].append(symbol)
    items: list[CatalogItem] = []
    file_card_ids: dict[str, str] = {}

    for symbol in sorted(symbols, key=lambda row: (str(row.get("file_path")), str(row.get("qualified_name")))):
        path = str(symbol.get("file_path") or "")
        source_ids = tuple(filter(None, [symbol.get("evidence_id")]))
        unknowns = () if symbol.get("signature") else ("未提取到完整签名",)
        items.append(CatalogItem(
            id=_id(snapshot_id, "symbol", str(symbol["id"])), repo_id=repo_id, snapshot_id=snapshot_id,
            kind="symbol", title=str(symbol.get("qualified_name") or symbol.get("name") or "symbol"),
            path=path, parent_id=None,
            summary=f"{symbol.get('symbol_kind', 'symbol')} {symbol.get('qualified_name') or symbol.get('name')}，位于 {path}。",
            details={"symbol_id": symbol["id"], "symbol_kind": symbol.get("symbol_kind"), "signature": symbol.get("signature"),
                     "start_line": symbol.get("start_line"), "end_line": symbol.get("end_line")},
            source_evidence_ids=source_ids, known_unknowns=unknowns,
        ))

    for file in sorted(files, key=lambda row: str(row.get("relative_path"))):
        path = str(file.get("relative_path") or "")
        rows, file_symbols = by_path.get(path, []), symbols_by_path.get(path, [])
        categories = []
        if _is_entry(path, file_symbols): categories.append("entry_point")
        if bool(file.get("is_test_file")): categories.append("test")
        if _is_config(file): categories.append("configuration")
        if not categories: categories.append("module")
        source_ids = _evidence_ids(rows)
        known_unknowns = []
        if not source_ids: known_unknowns.append("该文件没有可绑定的解析 Evidence")
        if file.get("parse_status") not in {None, "parsed", "success", "succeeded"}: known_unknowns.append(f"解析状态为 {file.get('parse_status')}")
        card_id = _id(snapshot_id, "file", path)
        file_card_ids[path] = card_id
        summary = f"{path}：{file.get('language') or 'unknown'} 文件，分类为 {', '.join(categories)}，包含 {len(file_symbols)} 个符号。"
        items.append(CatalogItem(
            id=card_id, repo_id=repo_id, snapshot_id=snapshot_id, kind="file", title=path, path=path,
            parent_id=None, summary=summary,
            details={"file_id": file.get("id"), "language": file.get("language"), "categories": categories,
                     "symbol_count": len(file_symbols), "line_count": file.get("line_count")},
            source_evidence_ids=source_ids, known_unknowns=tuple(known_unknowns),
        ))

    directories: dict[str, list[dict]] = defaultdict(list)
    for file in files:
        path = str(file.get("relative_path") or "")
        directory = _directory(path)
        while directory:
            directories[directory].append(file)
            directory = _directory(directory)
    directory_ids: dict[str, str] = {}
    for directory, directory_files in sorted(directories.items()):
        source_rows = [row for file in directory_files for row in by_path.get(str(file.get("relative_path") or ""), [])]
        languages = Counter(str(file.get("language") or "unknown") for file in directory_files)
        card_id = _id(snapshot_id, "directory", directory)
        directory_ids[directory] = card_id
        items.append(CatalogItem(
            id=card_id, repo_id=repo_id, snapshot_id=snapshot_id, kind="directory", title=directory, path=directory,
            parent_id=None, summary=f"目录 {directory} 包含 {len(directory_files)} 个文件，主要语言为 {', '.join(name for name, _ in languages.most_common(3))}。",
            details={"file_count": len(directory_files), "language_counts": dict(languages)},
            source_evidence_ids=_evidence_ids(source_rows),
            known_unknowns=() if source_rows else ("目录内没有可用 Evidence",),
        ))

    # 将同一顶层目录作为可导航 subsystem；根目录文件归入 root subsystem。
    subsystems: dict[str, list[dict]] = defaultdict(list)
    for file in files:
        path = str(file.get("relative_path") or "")
        parts = PurePosixPath(path).parts
        subsystems[parts[0] if len(parts) > 1 else "root"].append(file)
    for name, subsystem_files in sorted(subsystems.items()):
        source_rows = [row for file in subsystem_files for row in by_path.get(str(file.get("relative_path") or ""), [])]
        items.append(CatalogItem(
            id=_id(snapshot_id, "subsystem", name), repo_id=repo_id, snapshot_id=snapshot_id,
            kind="subsystem", title=f"{name} subsystem", path=None if name == "root" else name, parent_id=None,
            summary=f"{name} 子系统由 {len(subsystem_files)} 个文件组成。",
            details={"file_paths": sorted(str(file.get("relative_path")) for file in subsystem_files)},
            source_evidence_ids=_evidence_ids(source_rows), known_unknowns=() if source_rows else ("子系统职责需人工确认",),
        ))

    language_counts = Counter(str(file.get("language") or "unknown") for file in files)
    entry_points = sorted(str(file.get("relative_path")) for file in files if _is_entry(str(file.get("relative_path") or ""), symbols_by_path.get(str(file.get("relative_path") or ""), [])))
    config_files = sorted(str(file.get("relative_path")) for file in files if _is_config(file))
    test_files = sorted(str(file.get("relative_path")) for file in files if bool(file.get("is_test_file")))
    module_files = sorted(str(file.get("relative_path")) for file in files if not file.get("is_test_file") and not _is_config(file))
    overview_id = _id(snapshot_id, "repository_overview", repo_id)
    overview_unknowns = []
    if not entry_points: overview_unknowns.append("未识别到明确入口文件")
    if not test_files: overview_unknowns.append("未识别到测试文件")
    if not config_files: overview_unknowns.append("未识别到配置文件")
    items.append(CatalogItem(
        id=overview_id, repo_id=repo_id, snapshot_id=snapshot_id, kind="repository_overview",
        title=f"{repo.get('alias') or repo_id} Overview", path=None, parent_id=None,
        summary=f"仓库包含 {len(files)} 个文件、{len(symbols)} 个符号、{len(directories)} 个目录；主要语言为 {', '.join(name for name, _ in language_counts.most_common(5))}。",
        details={"language_counts": dict(language_counts), "entry_points": entry_points, "configuration_files": config_files,
                 "test_files": test_files, "module_files": module_files, "subsystems": sorted(subsystems)},
        source_evidence_ids=_evidence_ids(evidence), known_unknowns=tuple(overview_unknowns),
    ))
    reading_order = list(dict.fromkeys(entry_points + config_files + module_files + test_files))
    items.append(CatalogItem(
        id=_id(snapshot_id, "reading_guide", repo_id), repo_id=repo_id, snapshot_id=snapshot_id,
        kind="reading_guide", title="Reading Guide", path=None, parent_id=overview_id,
        summary="建议先读入口，再读配置与核心模块，最后用测试验证行为。",
        details={"reading_order": reading_order, "steps": [
            {"stage": "entry_points", "paths": entry_points}, {"stage": "configuration", "paths": config_files},
            {"stage": "modules", "paths": module_files}, {"stage": "tests", "paths": test_files},
        ]}, source_evidence_ids=_evidence_ids(evidence),
        known_unknowns=("阅读顺序来自路径和符号规则，未包含运行时调用频率",),
    ))

    # 在所有卡片创建后补齐父级，保证 tree API 可从 overview 下钻到 subsystem/directory/file/symbol。
    lookup = {item.id: item for item in items}
    rebuilt: list[CatalogItem] = []
    for item in items:
        parent = item.parent_id
        if item.kind == "subsystem": parent = overview_id
        elif item.kind == "directory":
            top = PurePosixPath(item.path or "").parts[0] if item.path else "root"
            parent = _id(snapshot_id, "subsystem", top)
        elif item.kind == "file":
            directory = _directory(item.path or "")
            parent = directory_ids.get(directory) or _id(snapshot_id, "subsystem", "root")
        elif item.kind == "symbol": parent = file_card_ids.get(item.path or "")
        if parent == item.parent_id:
            rebuilt.append(item)
        else:
            rebuilt.append(CatalogItem(**{**item.__dict__, "parent_id": parent}))
    return rebuilt


def build_catalog(repo: dict, snapshot: dict, files: list[dict], evidence: list[dict], symbols: list[dict], *, enhance: bool = False) -> list[CatalogItem]:
    """默认只构建规则版；显式开启时尝试 LLM 增强并自动降级。"""
    items = build_rule_catalog(repo, snapshot, files, evidence, symbols)
    return enhance_catalog_items(items) if enhance else items
