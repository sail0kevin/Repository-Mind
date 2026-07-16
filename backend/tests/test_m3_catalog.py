"""M3 Repository Catalog 规则构建、API 和快照隔离测试。"""
from pathlib import Path

from fastapi.testclient import TestClient

from service.core.catalog.builder import build_catalog
from service.main import create_app
from service.storage.catalog_store import replace_snapshot_catalog
from service.storage.evidence_store import replace_snapshot_parse_results
from service.storage.repository_store import create_repo_record, replace_file_records
from service.storage.snapshot_store import get_or_create_snapshot, publish_snapshot
from service.storage.sqlite_db import get_connection


def _seed_catalog_snapshot(tmp_path: Path, repo_id: str, commit: str, suffix: str):
    snapshot, _ = get_or_create_snapshot(repo_id, commit, "main")
    files = [
        {"relative_path": "src/main.py", "language": "python", "file_type": "text", "extension": ".py", "line_count": 8, "is_binary": False, "is_test_file": False, "parse_status": "parsed"},
        {"relative_path": "src/service.py", "language": "python", "file_type": "text", "extension": ".py", "line_count": 12, "is_binary": False, "is_test_file": False, "parse_status": "parsed"},
        {"relative_path": "tests/test_service.py", "language": "python", "file_type": "text", "extension": ".py", "line_count": 6, "is_binary": False, "is_test_file": True, "parse_status": "parsed"},
        {"relative_path": "pyproject.toml", "language": "toml", "file_type": "text", "extension": ".toml", "line_count": 5, "is_binary": False, "is_test_file": False, "parse_status": "parsed"},
        {"relative_path": "web/index.ts", "language": "typescript", "file_type": "text", "extension": ".ts", "line_count": 4, "is_binary": False, "is_test_file": False, "parse_status": "parsed"},
    ]
    replace_file_records(repo_id, files, snapshot_id=snapshot["id"])
    evidence, symbols = [], []
    with get_connection() as connection:
        rows = connection.execute("SELECT id, relative_path FROM files WHERE snapshot_id = ?", (snapshot["id"],)).fetchall()
    for index, row in enumerate(rows):
        evidence_id = f"ev_{suffix}_{index}"
        unit = {"id": evidence_id, "logical_id": evidence_id, "identity_key": evidence_id,
                "snapshot_id": snapshot["id"], "file_id": row["id"], "unit_type": "file",
                "content": f"content {row['relative_path']}", "parser_name": "test", "parser_version": "1"}
        file_symbols = []
        if row["relative_path"] == "src/main.py":
            file_symbols = [{"id": f"sym_{suffix}_main", "logical_id": f"sym_{suffix}_main",
                             "identity_key": f"sym_{suffix}_main", "snapshot_id": snapshot["id"],
                             "file_id": row["id"], "evidence_id": evidence_id,
                             "qualified_name": "src.main.main", "name": "main",
                             "symbol_kind": "function", "signature": "main()"}]
        elif row["relative_path"] == "src/service.py":
            file_symbols = [{"id": f"sym_{suffix}_service", "logical_id": f"sym_{suffix}_service",
                             "identity_key": f"sym_{suffix}_service", "snapshot_id": snapshot["id"],
                             "file_id": row["id"], "evidence_id": evidence_id,
                             "qualified_name": "src.service.run", "name": "run",
                             "symbol_kind": "function", "signature": "run()"}]
        replace_snapshot_parse_results(repo_id, snapshot["id"], row["id"], [unit], file_symbols, [], [])
        evidence.append({**unit, "file_path": row["relative_path"]})
        symbols.extend([{**item, "file_path": row["relative_path"]} for item in file_symbols])
    repo = {"id": repo_id, "alias": "catalog-demo"}
    items = build_catalog(repo, snapshot, files, evidence, symbols)
    replace_snapshot_catalog(repo_id, snapshot["id"], items)
    assert publish_snapshot(repo_id, snapshot["id"], "main", len(files))
    return snapshot, items


def test_rule_catalog_is_complete_without_api_key(tmp_path):
    """无 Key 时仍覆盖入口、语言、配置、测试、模块，并绑定 Evidence IDs。"""
    repo_id = create_repo_record(tmp_path, "catalog-demo", current_commit="a" * 40)
    snapshot, items = _seed_catalog_snapshot(tmp_path, repo_id, "a" * 40, "a")
    overview = next(item for item in items if item.kind == "repository_overview")
    guide = next(item for item in items if item.kind == "reading_guide")
    kinds = {item.kind for item in items}

    assert {"symbol", "file", "directory", "subsystem", "repository_overview", "reading_guide"} <= kinds
    assert overview.generation_method == "rule" and overview.model is None and overview.token_count == 0
    assert overview.freshness == "current_snapshot" and overview.snapshot_id == snapshot["id"]
    assert "src/main.py" in overview.details["entry_points"]
    assert "pyproject.toml" in overview.details["configuration_files"]
    assert "tests/test_service.py" in overview.details["test_files"]
    assert "src/service.py" in overview.details["module_files"]
    assert overview.details["language_counts"]["python"] == 3
    assert overview.source_evidence_ids and guide.source_evidence_ids
    assert guide.details["reading_order"][0] in {"src/main.py", "web/index.ts"}


def test_catalog_list_tree_detail_and_snapshot_isolation(tmp_path):
    """list/tree/detail 都只返回所选快照内容，历史卡片不会泄漏到 active。"""
    repo_id = create_repo_record(tmp_path, "catalog-demo", current_commit="a" * 40)
    first, first_items = _seed_catalog_snapshot(tmp_path, repo_id, "a" * 40, "a")
    second, second_items = _seed_catalog_snapshot(tmp_path, repo_id, "b" * 40, "b")
    first_overview = next(item for item in first_items if item.kind == "repository_overview")
    second_overview = next(item for item in second_items if item.kind == "repository_overview")

    with TestClient(create_app()) as client:
        active = client.get(f"/api/v1/repos/{repo_id}/catalog")
        tree = client.get(f"/api/v1/repos/{repo_id}/catalog/tree")
        detail = client.get(f"/api/v1/repos/{repo_id}/catalog/{second_overview.id}")
        historical = client.get(f"/api/v1/repos/{repo_id}/catalog/{first_overview.id}", params={"snapshot_id": first["id"]})
        leaked = client.get(f"/api/v1/repos/{repo_id}/catalog/{first_overview.id}")

    assert active.status_code == tree.status_code == detail.status_code == historical.status_code == 200
    assert active.json()["snapshot_id"] == second["id"]
    assert {item["snapshot_id"] for item in active.json()["items"]} == {second["id"]}
    assert tree.json()["roots"] and any(root["kind"] == "repository_overview" for root in tree.json()["roots"])
    assert detail.json()["source_evidence_ids"]
    assert historical.json()["snapshot_id"] == first["id"]
    assert leaked.status_code == 404
