"""M2 stage2 生产 ingest 与产品查询验收测试。"""
from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from service.core.ingest_service import ingest_repository_snapshot
from service.main import create_app
from service.storage.repository_store import create_repo_record, get_repo_record
from service.storage.snapshot_store import create_or_get_snapshot, finish_snapshot, get_snapshot
from service.storage.sqlite_db import get_connection


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def _commit(repo: Path, message: str) -> str:
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.com",
                    "commit", "-m", message], check=True, stdout=subprocess.DEVNULL)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def stage2_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "stage2-repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, stdout=subprocess.DEVNULL)
    (repo / "app.py").write_text(
        "import helper\n\ndef run():\n    return helper.value()\n", encoding="utf-8",
    )
    (repo / "helper.py").write_text("def value():\n    return 'needle'\n", encoding="utf-8")
    (repo / "broken.json").write_text("{", encoding="utf-8")
    _commit(repo, "first")
    return repo


def _register(repo: Path) -> str:
    return create_repo_record(repo, alias=repo.name, current_commit=_git(repo, "rev-parse", "HEAD"))


def test_production_ingest_creates_canonical_facts_and_compatible_projections(stage2_repo: Path) -> None:
    repo_id = _register(stage2_repo)
    result = ingest_repository_snapshot(repo_id)
    with get_connection() as connection:
        counts = {table: connection.execute(
            f"SELECT COUNT(*) FROM {table} WHERE snapshot_id = ?", (result.snapshot_id,)
        ).fetchone()[0] for table in (
            "evidence_units", "symbols", "relations", "parser_diagnostics", "chunks", "code_nodes",
        )}
        statuses = {row[0] for row in connection.execute(
            "SELECT parse_status FROM files WHERE snapshot_id = ? AND ignored_reason IS NULL", (result.snapshot_id,)
        ).fetchall()}
    assert counts["evidence_units"] > 0
    assert counts["symbols"] > 0
    assert counts["relations"] > 0
    assert counts["parser_diagnostics"] > 0
    assert counts["chunks"] == counts["evidence_units"]
    assert counts["code_nodes"] == counts["symbols"]
    assert statuses <= {"parsed", "parsed_with_errors", "fallback_text", "unsupported", "failed"}
    assert "fallback_text" in statuses


def test_projection_failure_does_not_publish_and_retry_cleans_canonical_facts(stage2_repo: Path,
                                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    repo_id = _register(stage2_repo)
    real_project = __import__("service.core.ingest_service", fromlist=["project_symbols_to_code_graph"]).project_symbols_to_code_graph
    monkeypatch.setattr("service.core.ingest_service.project_symbols_to_code_graph",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("projection failed")))
    with pytest.raises(RuntimeError, match="projection failed"):
        ingest_repository_snapshot(repo_id)
    failed_id = create_or_get_snapshot(repo_id, _git(stage2_repo, "rev-parse", "HEAD"))["id"]
    assert get_snapshot(failed_id)["status"] == "failed"
    assert get_repo_record(repo_id)["active_snapshot_id"] is None

    monkeypatch.setattr("service.core.ingest_service.project_symbols_to_code_graph", real_project)
    retried = ingest_repository_snapshot(repo_id)
    assert retried.snapshot_id == failed_id
    assert get_snapshot(failed_id)["status"] == "succeeded"


def test_product_apis_reject_non_succeeded_and_cross_repo_and_return_snapshot(stage2_repo: Path) -> None:
    repo_id = _register(stage2_repo)
    result = ingest_repository_snapshot(repo_id)
    other_repo = "repo_other_scope"
    with get_connection() as connection:
        connection.execute(
            "INSERT INTO repos (id, alias, repo_path, status) VALUES (?, ?, ?, 'ready')",
            (other_repo, "other", str(stage2_repo.parent / "other-repo")),
        )
    building = create_or_get_snapshot(repo_id, "b" * 40)
    failed = create_or_get_snapshot(repo_id, "c" * 40)
    assert finish_snapshot(failed["id"], "failed", "boom")

    with TestClient(create_app()) as client:
        for snapshot_id in (building["id"], failed["id"]):
            assert client.get(f"/api/v1/repos/{repo_id}/evidence", params={"snapshot_id": snapshot_id}).status_code == 409
            assert client.get(f"/api/v1/code-graph/{repo_id}/stats", params={"snapshot_id": snapshot_id}).status_code == 409
        assert client.get(f"/api/v1/repos/{other_repo}/symbols", params={"snapshot_id": result.snapshot_id}).status_code == 404
        evidence = client.get(f"/api/v1/repos/{repo_id}/evidence")
        relations = client.get(f"/api/v1/repos/{repo_id}/relations")
        diagnostics = client.get(f"/api/v1/repos/{repo_id}/parser-diagnostics")
        graph = client.get(f"/api/v1/code-graph/{repo_id}/stats")
    for response in (evidence, relations, diagnostics, graph):
        assert response.status_code == 200
        assert response.json()["snapshot_id"] == result.snapshot_id
    assert evidence.json()["items"] and relations.json()["items"] and diagnostics.json()["items"]


def test_legacy_chunk_null_fields_are_normalized(stage2_repo: Path) -> None:
    repo_id = _register(stage2_repo)
    result = ingest_repository_snapshot(repo_id)
    with get_connection() as connection:
        connection.execute(
            """INSERT INTO chunks (id, repo_id, snapshot_id, file_id, file_path, chunk_type, content,
                    content_hash, embedding_status, source_type)
               VALUES ('legacy-null', ?, ?, NULL, NULL, NULL, NULL, NULL, NULL, NULL)""",
            (repo_id, result.snapshot_id),
        )
    with TestClient(create_app()) as client:
        response = client.get(f"/api/v1/repos/{repo_id}/chunks/legacy-null",
                              params={"snapshot_id": result.snapshot_id})
    assert response.status_code == 200
    body = response.json()
    assert body["snapshot_id"] == result.snapshot_id
    assert body["file_id"] == body["file_path"] == body["content"] == body["content_hash"] == ""



def test_post_publish_progress_failure_does_not_fail_snapshot(stage2_repo: Path) -> None:
    """publish 后的最终通知异常不能把已成功快照回写成 failed。"""
    repo_id = _register(stage2_repo)
    def callback(progress, _message=None):
        if progress == 1.0:
            raise RuntimeError("listener gone")
    result = ingest_repository_snapshot(repo_id, progress_callback=callback)
    assert result.status == "succeeded"
    assert get_snapshot(result.snapshot_id)["status"] == "succeeded"
    assert get_repo_record(repo_id)["active_snapshot_id"] == result.snapshot_id


def test_ingest_reuses_scanner_bytes_for_one_read_per_indexable_file(stage2_repo: Path,
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    """scanner 捕获的可索引字节应直接交给 ingest，每个文件只 read_bytes 一次。"""
    repo_id = _register(stage2_repo)
    real_read = Path.read_bytes
    counts: dict[str, int] = {}
    def counted(path: Path):
        if path.is_relative_to(stage2_repo):
            counts[path.relative_to(stage2_repo).as_posix()] = counts.get(path.relative_to(stage2_repo).as_posix(), 0) + 1
        return real_read(path)
    monkeypatch.setattr(Path, "read_bytes", counted)
    ingest_repository_snapshot(repo_id)
    indexable = {"app.py", "helper.py", "broken.json"}
    assert indexable <= counts.keys()
    assert all(counts[path] == 1 for path in indexable), counts
