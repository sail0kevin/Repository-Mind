"""TypeScript parse facts must reach the snapshot-scoped code graph APIs."""
from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from service.core.ingest_service import ingest_repository_snapshot
from service.main import create_app
from service.storage.repository_store import create_repo_record
from service.storage.sqlite_db import get_connection


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def _commit(repo: Path, message: str) -> str:
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", message],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    return _git(repo, "rev-parse", "HEAD")


def _graph_nodes(repo_id: str, snapshot_id: str) -> list[dict]:
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT name, node_type FROM code_nodes WHERE repo_id = ? AND snapshot_id = ? ORDER BY name",
            (repo_id, snapshot_id),
        ).fetchall()
    return [dict(row) for row in rows]


def _graph_edge_types(repo_id: str, snapshot_id: str) -> set[str]:
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT edge_type FROM code_edges WHERE repo_id = ? AND snapshot_id = ?",
            (repo_id, snapshot_id),
        ).fetchall()
    return {row["edge_type"] for row in rows}


def test_typescript_ingest_projects_graph_and_preserves_historical_snapshot(tmp_path: Path) -> None:
    """A controlled Git fixture proves graph ingest without executing its source code."""
    repo = tmp_path / "typescript-graph-repo"
    (repo / "src").mkdir(parents=True)
    subprocess.run(["git", "init", str(repo)], check=True, stdout=subprocess.DEVNULL)
    (repo / "src" / "helpers.ts").write_text(
        "export function helper(value: string): string {\n    return value.toUpperCase();\n}\n",
        encoding="utf-8",
    )
    (repo / "src" / "main.ts").write_text(
        "import { helper } from './helpers';\n\n"
        "export class Worker {\n"
        "    run(value: string): string {\n"
        "        return helper(value);\n"
        "    }\n"
        "}\n\n"
        "export function start(value: string): string {\n"
        "    return new Worker().run(value);\n"
        "}\n",
        encoding="utf-8",
    )
    _commit(repo, "initial TypeScript graph")
    repo_id = create_repo_record(repo, alias=repo.name, current_commit=_git(repo, "rev-parse", "HEAD"))

    first = ingest_repository_snapshot(repo_id)
    first_nodes = _graph_nodes(repo_id, first.snapshot_id)
    if not first_nodes:
        # Native grammar packages are optional. Their absence must not invent graph structure.
        with get_connection() as connection:
            diagnostics = connection.execute(
                "SELECT code FROM parser_diagnostics WHERE snapshot_id = ?", (first.snapshot_id,)
            ).fetchall()
        assert {row["code"] for row in diagnostics} == {"tree_sitter_unavailable"}
        return

    assert {("class", "Worker"), ("function", "helper"), ("function", "start"), ("method", "run")} <= {
        (item["node_type"], item["name"]) for item in first_nodes
    }
    assert "contains" in _graph_edge_types(repo_id, first.snapshot_id)

    with TestClient(create_app()) as client:
        first_stats = client.get(f"/api/v1/code-graph/{repo_id}/stats")
        first_search = client.get(f"/api/v1/code-graph/{repo_id}/search", params={"q": "Worker"})

    assert first_stats.status_code == first_search.status_code == 200
    assert first_stats.json()["snapshot_id"] == first.snapshot_id
    assert first_stats.json()["classes"] >= 1
    assert first_stats.json()["total_edges"] >= 1
    assert first_search.json()["snapshot_id"] == first.snapshot_id
    assert [item["name"] for item in first_search.json()["matches"]] == ["Worker"]

    (repo / "src" / "main.ts").write_text(
        "import { helper } from './helpers';\n\n"
        "export class Processor {\n"
        "    execute(value: string): string {\n"
        "        return helper(value);\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    _commit(repo, "replace Worker")
    second = ingest_repository_snapshot(repo_id)

    with TestClient(create_app()) as client:
        active_worker = client.get(f"/api/v1/code-graph/{repo_id}/search", params={"q": "Worker"})
        historical_worker = client.get(
            f"/api/v1/code-graph/{repo_id}/search",
            params={"q": "Worker", "snapshot_id": first.snapshot_id},
        )
        active_processor = client.get(f"/api/v1/code-graph/{repo_id}/search", params={"q": "Processor"})

    assert all(response.status_code == 200 for response in (active_worker, historical_worker, active_processor))
    assert active_worker.json()["snapshot_id"] == second.snapshot_id
    assert active_worker.json()["matches"] == []
    assert historical_worker.json()["snapshot_id"] == first.snapshot_id
    assert [item["name"] for item in historical_worker.json()["matches"]] == ["Worker"]
    assert active_processor.json()["snapshot_id"] == second.snapshot_id
    assert [item["name"] for item in active_processor.json()["matches"]] == ["Processor"]
