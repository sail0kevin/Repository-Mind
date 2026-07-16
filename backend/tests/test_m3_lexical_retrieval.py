"""M3 FTS5 词法检索、快照隔离和离线排名基线测试。"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from service.storage.chunk_store import replace_repo_chunks, search_chunks
from service.storage.lexical_store import normalize_query
from service.storage.repository_store import create_repo_record
from service.storage.snapshot_store import get_or_create_snapshot, publish_snapshot
from service.storage.sqlite_db import get_connection, require_fts5


def _seed_baseline(tmp_path: Path) -> tuple[str, str, str]:
    """建立两个快照，active 中包含评测目标，旧快照含同词干扰项。"""
    repo_id = create_repo_record(tmp_path / "retrieval-repo", alias="m3-retrieval")
    snapshot, _ = get_or_create_snapshot(repo_id, "a" * 40, "main")
    active_id = snapshot["id"]
    replace_repo_chunks(
        repo_id,
        {
            "fixture": [
                {"file_path": "src/config_loader.py", "chunk_type": "python", "title": "配置解析", "symbol_name": "parseConfigKey", "content": "def parse_config_key(value): return value", "content_hash": "1"},
                {"file_path": "src/auth/token_service.py", "chunk_type": "python", "title": "用户认证服务", "symbol_name": "TokenService", "content": "用户认证 token validation login", "content_hash": "2"},
                {"file_path": "config/database.yaml", "chunk_type": "yaml", "title": "database settings", "symbol_name": "database.timeout", "content": "database_timeout: 30", "content_hash": "3"},
                {"file_path": "src/noise.py", "chunk_type": "python", "title": "noise", "symbol_name": "unrelated", "content": "parse database user helper", "content_hash": "4"},
            ]
        },
        snapshot_id=active_id,
    )
    publish_snapshot(repo_id, active_id, "main", 4)

    old_snapshot, _ = get_or_create_snapshot(repo_id, "b" * 40, "old")
    old_id = old_snapshot["id"]
    replace_repo_chunks(
        repo_id,
        {"old": [{"file_path": "legacy/secret.py", "chunk_type": "python", "title": "legacy", "symbol_name": "parseConfigKey", "content": "用户认证 database timeout", "content_hash": "old"}]},
        snapshot_id=old_id,
    )
    return repo_id, active_id, old_id


def _metrics(ranked: list[list[str]], relevant: list[set[str]]) -> tuple[float, float, float]:
    """计算 Recall@5、Recall@10 和 MRR，作为后续混合检索可复现基线。"""
    recall5 = sum(bool(set(items[:5]) & expected) for items, expected in zip(ranked, relevant)) / len(ranked)
    recall10 = sum(bool(set(items[:10]) & expected) for items, expected in zip(ranked, relevant)) / len(ranked)
    reciprocal = []
    for items, expected in zip(ranked, relevant):
        reciprocal.append(next((1 / rank for rank, item in enumerate(items, 1) if item in expected), 0.0))
    return recall5, recall10, sum(reciprocal) / len(reciprocal)


def test_query_normalization_covers_chinese_snake_camel_and_path() -> None:
    """归一化应保留中文短语，并展开 snake、camel 和 Windows/POSIX 路径。"""
    terms = normalize_query(r"用户认证 parseConfigKey parse_config_key src\auth/token_service.py")
    assert {"用户认证", "用", "户", "认", "证", "parseconfigkey", "parse", "config", "key", "src", "auth", "token", "service", "py"} <= set(terms)


def test_fts5_capability_check_has_clear_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """启动能力检测失败时必须转换成明确的 FTS5 错误。"""
    connection = sqlite3.connect(":memory:")
    original = connection.execute

    class BrokenConnection:
        def execute(self, sql, parameters=()):
            if "fts5" in sql.lower():
                raise sqlite3.OperationalError("no such module: fts5")
            return original(sql, parameters)

    with pytest.raises(RuntimeError, match="FTS5"):
        require_fts5(BrokenConnection())
    connection.close()


def test_snapshot_isolation_exact_boost_and_run_tracking(tmp_path: Path) -> None:
    """默认只搜 active，精确标识符应排第一，并持久化 run/candidate。"""
    repo_id, active_id, old_id = _seed_baseline(tmp_path)
    active_hits = search_chunks(repo_id, "parseConfigKey", limit=5)
    old_hits = search_chunks(repo_id, "parseConfigKey", limit=5, snapshot_id=old_id)

    assert active_hits[0]["file_path"] == "src/config_loader.py"
    assert "legacy/secret.py" not in {item["file_path"] for item in active_hits}
    assert {item["file_path"] for item in old_hits} == {"legacy/secret.py"}
    assert all(item["snapshot_id"] == active_id for item in active_hits)
    old_run_id = old_hits[0]["retrieval_run_id"]
    with get_connection() as connection:
        run = connection.execute("SELECT * FROM retrieval_runs WHERE id = ?", (old_run_id,)).fetchone()
        candidates = connection.execute("SELECT * FROM retrieval_candidates WHERE run_id = ?", (old_run_id,)).fetchall()
    assert run["snapshot_id"] == old_id
    assert run["normalized_query"] == "parseconfigkey parse config key"
    assert len(candidates) == 1
    assert candidates[0]["exact_boost"] > 0


def test_recall_at_5_10_and_mrr_baseline(tmp_path: Path) -> None:
    """固定 fixture 的 Recall@5/10 必须满分，MRR 保持为 1.0。"""
    repo_id, _, _ = _seed_baseline(tmp_path)
    fixture_path = Path(__file__).parent / "fixtures" / "m3_lexical_baseline.json"
    cases = json.loads(fixture_path.read_text(encoding="utf-8"))["queries"]
    ranked, relevant = [], []
    for case in cases:
        ranked.append([item["file_path"] for item in search_chunks(repo_id, case["query"], limit=10)])
        relevant.append(set(case["relevant"]))
    recall5, recall10, mrr = _metrics(ranked, relevant)
    assert recall5 == 1.0
    assert recall10 == 1.0
    assert mrr == 1.0
