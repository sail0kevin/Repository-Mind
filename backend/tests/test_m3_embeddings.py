"""验证 M3 provider-neutral Embedding、缓存、降级和设置安全契约。"""
from __future__ import annotations

from array import array
from types import SimpleNamespace

from fastapi.testclient import TestClient

from service.core.embeddings.base import EmbeddingError, EmbeddingProvider
from service.core.embeddings.openai_compatible import OpenAICompatibleEmbeddingProvider
from service.core.embeddings.service import embed_snapshot_evidence, resolve_embedding_provider
from service.main import create_app
from service.storage.repository_store import create_repo_record
from service.storage.secret_store import MemorySecretStore, get_secret_store, set_secret_store
from service.storage.settings_store import get_setting, set_setting
from service.storage.snapshot_store import get_or_create_snapshot
from service.storage.sqlite_db import get_connection


class FakeProvider(EmbeddingProvider):
    name = "fake"
    model = "fake-v1"
    enabled = True

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]):
        from service.core.embeddings.base import EmbeddingBatch
        self.calls.append(texts)
        return EmbeddingBatch([[float(len(text)), 0.5] for text in texts], self.name, self.model)


def _seed_snapshot(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    repo_id = create_repo_record(str(repo), alias="demo")
    snapshot, _ = get_or_create_snapshot(repo_id, "abc123", "main")
    with get_connection() as connection:
        connection.execute("INSERT INTO files (id, repo_id, snapshot_id, relative_path) VALUES ('file1', ?, ?, 'a.py')", (repo_id, snapshot["id"]))
        for item in ({"id": "ev1", "hash": "h1", "content": "alpha"}, {"id": "ev2", "hash": "h2", "content": "beta"}):
            connection.execute("""INSERT INTO evidence_units
                (id, logical_id, snapshot_id, file_id, unit_type, identity_key,
                 content, content_hash, parser_name, parser_version)
                VALUES (?, ?, ?, 'file1', 'code', ?, ?, ?, 'test', '1')""",
                (item["id"], item["id"], snapshot["id"], item["id"], item["content"], item["hash"]))
            connection.execute("""INSERT INTO chunks
                (id, repo_id, snapshot_id, file_id, content, content_hash, embedding_status)
                VALUES (?, ?, ?, 'file1', ?, ?, 'pending')""",
                (item["id"], repo_id, snapshot["id"], item["content"], item["hash"]))
    return repo_id, snapshot["id"]


def test_openai_compatible_sdk_contract_orders_response_and_sends_float():
    captured = {}

    class Embeddings:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(data=[SimpleNamespace(index=1, embedding=[3, 4]), SimpleNamespace(index=0, embedding=[1, 2])])

    def factory(**kwargs):
        captured["client"] = kwargs
        return SimpleNamespace(embeddings=Embeddings())

    provider = OpenAICompatibleEmbeddingProvider(api_key="emb-key", base_url="http://mock.local/v1", model="emb-model", client_factory=factory)
    result = provider.embed(["a", "b"])

    assert captured["client"] == {"api_key": "emb-key", "base_url": "http://mock.local/v1", "timeout": 60.0}
    assert captured["model"] == "emb-model"
    assert captured["input"] == ["a", "b"]
    assert captured["encoding_format"] == "float"
    assert result.vectors == [[1.0, 2.0], [3.0, 4.0]]


def test_disabled_default_does_not_create_placeholder_vectors(tmp_path):
    repo_id, snapshot_id = _seed_snapshot(tmp_path)
    result = embed_snapshot_evidence(repo_id, snapshot_id, [{"id": "ev1", "content": "alpha", "content_hash": "h1"}])
    assert result.status == "disabled"
    with get_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM evidence_embeddings").fetchone()[0] == 0
        assert connection.execute("SELECT DISTINCT embedding_status FROM chunks").fetchone()[0] == "disabled"


def test_float32_binding_and_cross_snapshot_cache_reuse(tmp_path):
    repo_id, snapshot_id = _seed_snapshot(tmp_path)
    provider = FakeProvider()
    evidence = [{"id": "ev1", "content": "alpha", "content_hash": "h1"}, {"id": "ev2", "content": "beta", "content_hash": "h2"}]
    first = embed_snapshot_evidence(repo_id, snapshot_id, evidence, provider=provider)
    assert first.stored == 2 and provider.calls == [["alpha", "beta"]]
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM evidence_embeddings WHERE evidence_id = 'ev1'").fetchone()
        assert row["snapshot_id"] == snapshot_id and row["provider"] == "fake" and row["model"] == "fake-v1"
        assert row["dimension"] == 2 and row["content_hash"] == "h1" and len(row["vector"]) == 8
        decoded = array("f"); decoded.frombytes(row["vector"])
        assert list(decoded) == [5.0, 0.5]
    second = embed_snapshot_evidence(repo_id, snapshot_id, evidence, provider=provider)
    assert second.reused == 2 and len(provider.calls) == 1


def test_provider_failure_is_warning_and_keeps_snapshot_data(tmp_path):
    repo_id, snapshot_id = _seed_snapshot(tmp_path)

    class Broken(FakeProvider):
        def embed(self, texts):
            raise EmbeddingError("mock outage")

    result = embed_snapshot_evidence(repo_id, snapshot_id, [{"id": "ev1", "content": "alpha", "content_hash": "h1"}], provider=Broken())
    assert result.status == "warning" and "mock outage" in result.warning
    with get_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM evidence_units").fetchone()[0] == 2
        assert connection.execute("SELECT DISTINCT embedding_status FROM chunks").fetchone()[0] == "warning"


def test_embedding_settings_key_is_separate_dpapi_secret_and_never_echoed():
    store = MemorySecretStore({"llm_api_key": "chat-secret"})
    set_secret_store(store)
    app = create_app()
    app.dependency_overrides[get_secret_store] = lambda: store
    try:
        with TestClient(app) as client:
            response = client.put("/api/v1/settings", json={
                "embedding_provider": "openai_compatible",
                "embedding_base_url": "http://mock.local/v1",
                "embedding_model": "emb-v1",
                "embedding_api_key_update": {"action": "set", "value": "embedding-secret-4321"},
            })
            assert response.status_code == 200
            payload = response.json()
            assert payload["embedding_api_key_configured"] is True
            assert payload["embedding_api_key_hint"] == "••••4321"
            assert "embedding-secret-4321" not in response.text
            assert store.get("embedding_api_key") == "embedding-secret-4321"
            assert store.get("llm_api_key") == "chat-secret"
            assert get_setting("embedding_api_key") is None
            provider = resolve_embedding_provider()
            assert provider.api_key == "embedding-secret-4321"
    finally:
        set_secret_store(None)
