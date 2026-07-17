"""工作流分析快照契约与导出字段的回归测试。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from service.main import create_app
from service.storage.analysis_store import get_analysis_report
from service.storage.chunk_store import list_chunk_records, replace_repo_chunks
from service.storage.repository_store import get_repo_record
from service.storage.snapshot_store import create_or_get_snapshot, finish_snapshot, set_active_snapshot
from service.api.v1.repos import _workflow_snapshot_files
from service.core import workflow_analysis
from service.core.workflow_analysis import build_workflow_report
from service.storage.sqlite_db import get_connection


def _seed_snapshots() -> tuple[str, str, str]:
    """创建一个 active 新快照和一个可显式读取的旧快照。"""
    repo_id = "repo_workflow_snapshots"
    old_commit = "1" * 40
    new_commit = "2" * 40
    with get_connection() as connection:
        connection.execute(
            "INSERT INTO repos (id, alias, repo_path, branch, commit_hash, status) VALUES (?, ?, ?, ?, ?, ?)",
            (repo_id, "工作流仓库", "/tmp/current-repo", "main", new_commit, "indexed"),
        )
    old_snapshot = create_or_get_snapshot(repo_id, old_commit, "old-branch")
    new_snapshot = create_or_get_snapshot(repo_id, new_commit, "main")
    assert finish_snapshot(old_snapshot["id"], "succeeded")
    assert finish_snapshot(new_snapshot["id"], "succeeded")
    assert set_active_snapshot(repo_id, new_snapshot["id"])

    with get_connection() as connection:
        connection.executemany(
            """
            INSERT INTO files (id, repo_id, snapshot_id, relative_path, absolute_path, file_type, language, size_bytes, parse_status)
            VALUES (?, ?, ?, ?, ?, 'text', 'python', 10, 'pending')
            """,
            [
                ("old-file", repo_id, old_snapshot["id"], "src/old.py", "/tmp/current-repo/src/old.py"),
                ("new-file", repo_id, new_snapshot["id"], "src/new.py", "/tmp/current-repo/src/new.py"),
                ("new-helper-file", repo_id, new_snapshot["id"], "src/new_helper.py", "/tmp/current-repo/src/new_helper.py"),
            ],
        )
    replace_repo_chunks(repo_id, {"src/old.py": [{
        "file_id": "old-file", "file_path": "src/old.py", "chunk_type": "module", "symbol_name": "old_only",
        "content": "def old_only():\n    return 'old'\n", "content_hash": "old", "source_type": "python",
    }]}, snapshot_id=old_snapshot["id"])
    replace_repo_chunks(repo_id, {
        "src/new.py": [{
            "file_id": "new-file", "file_path": "src/new.py", "chunk_type": "module", "symbol_name": "new_only",
            "content": "def new_only():\n    return 'new'\n", "content_hash": "new", "source_type": "python",
        }],
        "src/new_helper.py": [{
            "file_id": "new-helper-file", "file_path": "src/new_helper.py", "chunk_type": "module", "symbol_name": "new_helper_only",
            "content": "def new_helper_only():\n    return 'new helper'\n", "content_hash": "new-helper", "source_type": "python",
        }],
    }, snapshot_id=new_snapshot["id"])
    return repo_id, old_snapshot["id"], new_snapshot["id"]


def _finding_titles(body: dict) -> list[str]:
    return [finding["title"] for section in body["sections"] for finding in section["findings"]]


def _architecture_findings(body: dict) -> list[dict]:
    return next(section["findings"] for section in body["sections"] if section["key"] == "architecture")


def test_workflow_defaults_to_active_new_snapshot_and_accepts_explicit_old_snapshot():
    """旧客户端默认命中新 active；新客户端可稳定读取历史快照而不混入新文件。"""
    repo_id, old_snapshot_id, new_snapshot_id = _seed_snapshots()
    with TestClient(create_app()) as client:
        active_response = client.post(f"/api/v1/repos/{repo_id}/analysis/workflow", params={"auto_ingest": "false"})
        old_response = client.post(
            f"/api/v1/repos/{repo_id}/analysis/workflow",
            params={"auto_ingest": "false", "snapshot_id": old_snapshot_id},
        )

    assert active_response.status_code == old_response.status_code == 200
    active = active_response.json()
    old = old_response.json()
    assert active["snapshot_id"] == new_snapshot_id
    assert active["commit"] == "2" * 40
    active_architecture = _architecture_findings(active)
    assert active_architecture[0]["detail"].startswith("扫描到 2 个文件")
    assert len(active_architecture) == 3
    assert _finding_titles(active) == [
        "仓库结构概览", "代码结构线索：src/new.py", "代码结构线索：src/new_helper.py",
    ]
    assert "函数：new_only" in active_architecture[1]["detail"]
    assert "函数：new_helper_only" in active_architecture[2]["detail"]
    assert {chunk["symbol_name"] for chunk in list_chunk_records(repo_id, snapshot_id=new_snapshot_id)} == {
        "new_only", "new_helper_only",
    }
    assert old["snapshot_id"] == old_snapshot_id
    assert old["commit"] == "1" * 40
    assert old["repo"]["branch"] == "old-branch"
    old_architecture = _architecture_findings(old)
    assert old_architecture[0]["detail"].startswith("扫描到 1 个文件")
    assert len(old_architecture) == 2
    assert _finding_titles(old) == ["仓库结构概览", "代码结构线索：src/old.py"]
    assert "函数：old_only" in old_architecture[1]["detail"]
    assert [chunk["symbol_name"] for chunk in list_chunk_records(repo_id, snapshot_id=old_snapshot_id)] == ["old_only"]
    assert active["repo"]["repo_path"] == "工作流仓库"
    assert old["repo"]["repo_path"] == "工作流仓库"
    assert "/tmp/current-repo" not in str(active)
    assert "/tmp/current-repo" not in str(old)


def test_workflow_report_never_exposes_absolute_repo_path_in_legacy_repo_path_field():
    """旧字段保留时也必须只返回安全别名，不能把别名中的路径泄露出去。"""
    report = build_workflow_report(
        {
            "id": "repo_path_alias", "alias": "C:\\Users\\alice\\private-repo", "repo_path": "C:\\Users\\alice\\private-repo",
            "remote_url": None, "branch": "main", "commit_hash": "3" * 40, "status": "indexed",
        },
        [],
    )

    assert report["repo"]["repo_path"] == "local-repository"
    assert report["repo"]["alias"] == "local-repository"
    assert "C:\\Users\\alice\\private-repo" not in str(report)


def test_workflow_snapshot_reconstruction_preserves_chunk_line_numbers():
    """有间隔的 chunks 重建时保留原始行号，避免安全证据整体偏移。"""
    repo_id, _old_snapshot_id, new_snapshot_id = _seed_snapshots()
    with get_connection() as connection:
        connection.execute(
            "UPDATE chunks SET start_line = 3, end_line = 4 WHERE repo_id = ? AND snapshot_id = ?",
            (repo_id, new_snapshot_id),
        )
    files = _workflow_snapshot_files(repo_id, new_snapshot_id)
    new_file = next(item for item in files if item["relative_path"] == "src/new.py")
    assert new_file["snapshot_content"].splitlines()[:2] == ["", ""]


def test_transformed_config_snapshot_is_marked_non_exact_without_fake_lines():
    """结构化配置 chunk 不是原始 YAML，工作流证据必须明确标记非精确且不声称行号。"""
    repo_id, _old_snapshot_id, new_snapshot_id = _seed_snapshots()
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO files (id, repo_id, snapshot_id, relative_path, absolute_path, file_type, language, size_bytes, parse_status)
            VALUES (?, ?, ?, ?, ?, 'text', 'yaml', 20, 'parsed')
            """,
            ("config-file", repo_id, new_snapshot_id, "config.yml", "/tmp/current-repo/config.yml"),
        )
    replace_repo_chunks(repo_id, {"config.yml": [{
        "file_id": "config-file", "file_path": "config.yml", "chunk_type": "config_value",
        "content": '"secret-value"', "content_hash": "config", "source_type": "config_value",
        "start_line": 8, "end_line": 8,
    }]}, snapshot_id=new_snapshot_id)

    files = _workflow_snapshot_files(repo_id, new_snapshot_id)
    config_file = next(item for item in files if item["relative_path"] == "config.yml")
    assert config_file["snapshot_source_exact"] is False
    evidence = workflow_analysis.evidence_for_file(config_file, 8, 8, "configuration scan")
    assert evidence["start_line"] is None
    assert evidence["end_line"] is None
    assert "normalized snapshot evidence" in evidence["reason"]


def test_normalized_package_json_is_analyzed_structurally_without_false_invalid() -> None:
    """规范化 package.json chunks 不应被拼接后 json.loads 并误报 JSON 无效。"""
    findings = workflow_analysis.configuration_agent([{
        "relative_path": "package.json", "file_type": "text", "language": "json", "ignored_reason": None,
        "snapshot_source_exact": False,
        "snapshot_content": '"build"\n"react"',
        "snapshot_chunks": [
            {"chunk_type": "config_object", "title": "scripts", "content": '{"build":"vite build"}'},
            {"chunk_type": "config_value", "symbol_name": "dependencies.react", "content": '"^18.3.1"'},
        ],
    }])

    assert len(findings) == 1
    assert "规范化配置证据" in findings[0].detail
    assert "无法据此精确验证原始文件格式" in findings[0].detail
    assert "解析失败" not in findings[0].detail
    assert findings[0].evidence[0]["start_line"] is None


def test_workflow_snapshot_files_pages_through_more_than_ten_thousand_files(monkeypatch) -> None:
    """>10000 个轻量文件记录也必须完整读取，不能停在历史固定上限。"""
    calls: list[int] = []
    total = 10001

    def fake_list_files(
        _repo_id: str,
        limit: int,
        snapshot_id: str,
        offset: int = 0,
    ) -> list[dict]:
        calls.append(offset)
        end = min(offset + limit, total)
        return [{
            "relative_path": f"src/file-{index:05d}.txt",
            "absolute_path": f"/tmp/src/file-{index:05d}.txt",
            "language": "text",
            "file_type": "text",
            "ignored_reason": None,
        } for index in range(offset, end)]

    monkeypatch.setattr("service.api.v1.repos.list_file_records", fake_list_files)
    monkeypatch.setattr("service.api.v1.repos.list_chunk_records", lambda *_args, **_kwargs: [])

    files = _workflow_snapshot_files("repo-many-files", "snapshot-many-files")

    assert calls == [0, 5000, 10000]
    assert len(files) == total
    assert files[-1]["relative_path"] == "src/file-10000.txt"
    assert files[-1]["snapshot_content"] == ""


def test_workflow_snapshot_files_pages_through_all_chunks(monkeypatch) -> None:
    """超过单页大小的快照会继续分页，不能静默丢弃后续 chunks。"""
    calls: list[int] = []
    monkeypatch.setattr("service.api.v1.repos.list_file_records", lambda *_args, **_kwargs: [{
        "relative_path": "src/app.py", "absolute_path": "/tmp/src/app.py", "language": "python",
        "file_type": "text", "ignored_reason": None,
    }])

    def fake_list_chunks(_repo_id: str, limit: int, snapshot_id: str, offset: int = 0) -> list[dict]:
        calls.append(offset)
        if offset == 0:
            return [{"id": f"chunk-{index}", "file_path": "src/app.py", "start_line": index + 1,
                     "content": f"line-{index}", "chunk_type": "module"} for index in range(limit)]
        if offset == limit:
            return [{"id": "last", "file_path": "src/app.py", "start_line": limit + 1,
                     "content": "last-line", "chunk_type": "module"}]
        return []

    monkeypatch.setattr("service.api.v1.repos.list_chunk_records", fake_list_chunks)
    files = _workflow_snapshot_files("repo-large", "snapshot-large")

    assert calls == [0, 5000]
    assert len(files[0]["snapshot_chunks"]) == 5001
    assert files[0]["snapshot_content"].endswith("last-line")
    assert files[0]["snapshot_source_exact"] is True


def test_legacy_saved_workflow_report_backfills_snapshot_and_commit() -> None:
    """旧 report_json 缺少快照字段时从数据库绑定关系补齐并继续可读。"""
    repo_id, old_snapshot_id, _new_snapshot_id = _seed_snapshots()
    legacy_report = build_workflow_report(
        get_repo_record(repo_id), _workflow_snapshot_files(repo_id, old_snapshot_id),
        snapshot_id=old_snapshot_id, commit="1" * 40,
    )
    legacy_report.pop("snapshot_id")
    legacy_report.pop("commit")
    legacy_report.pop("response_type")
    import json
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO analysis_reports (id, repo_id, snapshot_id, analysis_type, status, summary, report_json, markdown)
            VALUES (?, ?, ?, 'workflow', 'succeeded', ?, ?, ?)
            """,
            (legacy_report["analysis_id"], repo_id, old_snapshot_id, legacy_report["summary"],
             json.dumps(legacy_report), legacy_report["markdown"]),
        )

    restored = get_analysis_report(legacy_report["analysis_id"])
    assert restored is not None
    assert restored["response_type"] == "workflow_report"
    assert restored["snapshot_id"] == old_snapshot_id
    assert restored["commit"] == "1" * 40
    with TestClient(create_app()) as client:
        response = client.get(f"/api/v1/analysis/{legacy_report['analysis_id']}")
    assert response.status_code == 200
    assert response.json()["snapshot_id"] == old_snapshot_id


def test_workflow_report_counts_selected_snapshot_chunks(monkeypatch):
    """报告 Repo Map 的 chunk 数必须查询选中快照，而不是隐式 active。"""
    repo_id, old_snapshot_id, _new_snapshot_id = _seed_snapshots()
    observed: list[tuple[str, str | None]] = []

    def fake_count_chunks(selected_repo_id: str, selected_snapshot_id: str | None = None) -> int:
        observed.append((selected_repo_id, selected_snapshot_id))
        return 7

    monkeypatch.setattr(workflow_analysis, "count_chunks", fake_count_chunks)
    repo = get_repo_record(repo_id)
    assert repo is not None
    files = _workflow_snapshot_files(repo_id, old_snapshot_id)
    build_workflow_report(repo, files, snapshot_id=old_snapshot_id, commit="1" * 40)

    assert observed == [(repo_id, old_snapshot_id)]
