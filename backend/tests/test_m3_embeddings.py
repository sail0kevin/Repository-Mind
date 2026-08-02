"""验证 M3 provider-neutral Embedding、缓存、降级和设置安全契约。"""
from __future__ import annotations

from array import array
from types import SimpleNamespace

from fastapi.testclient import TestClient

from service.core.embeddings import service as embedding_service_module
from service.core.embeddings.base import EmbeddingError, EmbeddingProvider
from service.core.embeddings.openai_compatible import OpenAICompatibleEmbeddingProvider
from service.core.embeddings.service import (
    embedding_query_configuration,
    embed_query,
    embed_snapshot_evidence,
    resolve_embedding_provider,
)
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
    first_request = {}
    factory_calls = 0

    class Embeddings:
        def create(self, **kwargs):
            captured.update(kwargs)
            if not first_request:
                first_request.update(kwargs)
            data = [SimpleNamespace(index=index, embedding=[index + 1, index + 2]) for index in range(len(kwargs["input"]))]
            if len(data) == 2:
                data.reverse()
            return SimpleNamespace(data=data)

    def factory(**kwargs):
        nonlocal factory_calls
        factory_calls += 1
        captured["client"] = kwargs
        return SimpleNamespace(embeddings=Embeddings())

    provider = OpenAICompatibleEmbeddingProvider(api_key="emb-key", base_url="http://mock.local/v1", model="emb-model", client_factory=factory)
    result = provider.embed(["a", "b"])
    second = provider.embed(["b"])

    assert factory_calls == 1
    assert captured["client"] == {"api_key": "emb-key", "base_url": "http://mock.local/v1", "timeout": 60.0}
    assert first_request["model"] == "emb-model"
    assert first_request["input"] == ["a", "b"]
    assert first_request["encoding_format"] == "float"
    assert result.vectors == [[1.0, 2.0], [2.0, 3.0]]
    assert second.vectors == [[1.0, 2.0]]


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


def test_embedding_input_limit_uses_truncated_content_for_cache_identity(tmp_path):
    repo_id, snapshot_id = _seed_snapshot(tmp_path)
    provider = FakeProvider()
    evidence = [{"id": "ev1", "content": "alphabet", "content_hash": "source-hash"}]

    first = embed_snapshot_evidence(
        repo_id, snapshot_id, evidence, provider=provider, max_input_characters=5,
    )
    second = embed_snapshot_evidence(
        repo_id, snapshot_id, evidence, provider=provider, max_input_characters=5,
    )

    assert first.stored == 1
    assert second.reused == 1
    assert provider.calls == [["alpha"]]
    with get_connection() as connection:
        stored_hash = connection.execute("SELECT content_hash FROM evidence_embeddings").fetchone()[0]
    import hashlib
    assert stored_hash == hashlib.sha256(b"alpha").hexdigest()


def test_embedding_batch_size_splits_provider_calls(tmp_path):
    repo_id, snapshot_id = _seed_snapshot(tmp_path)
    provider = FakeProvider()
    evidence = [
        {"id": "ev1", "content": "alpha", "content_hash": "h1"},
        {"id": "ev2", "content": "beta", "content_hash": "h2"},
    ]

    result = embed_snapshot_evidence(repo_id, snapshot_id, evidence, provider=provider, batch_size=1)

    assert result.stored == 2
    assert provider.calls == [["alpha"], ["beta"]]


def test_embedding_batch_failure_splits_and_uses_shorter_single_input(tmp_path):
    repo_id, snapshot_id = _seed_snapshot(tmp_path)

    class SelectivelyBroken(FakeProvider):
        def embed(self, texts):
            self.calls.append(texts)
            if len(texts) > 1 or any(text == "x" * 64 for text in texts):
                raise EmbeddingError("provider rejected input")
            from service.core.embeddings.base import EmbeddingBatch
            return EmbeddingBatch([[float(len(text)), 0.5] for text in texts], self.name, self.model)

    provider = SelectivelyBroken()
    evidence = [
        {"id": "ev1", "content": "alpha", "content_hash": "h1"},
        {"id": "ev2", "content": "x" * 64, "content_hash": "h2"},
    ]

    result = embed_snapshot_evidence(repo_id, snapshot_id, evidence, provider=provider)

    assert result.status == "ready"
    assert provider.calls == [["alpha", "x" * 64], ["alpha"], ["x" * 64], ["x" * 32]]
    with get_connection() as connection:
        row = connection.execute("SELECT content_hash FROM evidence_embeddings WHERE evidence_id = 'ev2'").fetchone()
    import hashlib
    assert row[0] == hashlib.sha256(("x" * 32).encode("utf-8")).hexdigest()


def test_embedding_short_input_tries_minimum_fallback_length(tmp_path):
    repo_id, snapshot_id = _seed_snapshot(tmp_path)

    class BrokenUntil32(FakeProvider):
        def embed(self, texts):
            self.calls.append(texts)
            if any(len(text) > 32 for text in texts):
                raise EmbeddingError("provider rejected input")
            from service.core.embeddings.base import EmbeddingBatch
            return EmbeddingBatch([[float(len(text)), 0.5] for text in texts], self.name, self.model)

    provider = BrokenUntil32()
    result = embed_snapshot_evidence(
        repo_id,
        snapshot_id,
        [{"id": "ev1", "content": "x" * 57, "content_hash": "h1"}],
        provider=provider,
    )

    assert result.status == "ready"
    assert provider.calls == [["x" * 57], ["x" * 32]]


def test_unrecoverable_embedding_keeps_successful_vectors(tmp_path):
    repo_id, snapshot_id = _seed_snapshot(tmp_path)

    class BrokenSecond(FakeProvider):
        def embed(self, texts):
            self.calls.append(texts)
            if any(text.startswith("beta") for text in texts):
                raise EmbeddingError("provider rejected beta")
            from service.core.embeddings.base import EmbeddingBatch
            return EmbeddingBatch([[float(len(text)), 0.5] for text in texts], self.name, self.model)

    result = embed_snapshot_evidence(
        repo_id,
        snapshot_id,
        [{"id": "ev1", "content": "alpha", "content_hash": "h1"}, {"id": "ev2", "content": "beta", "content_hash": "h2"}],
        provider=BrokenSecond(),
    )

    assert result.status == "warning"
    assert result.stored == 1
    with get_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM evidence_embeddings").fetchone()[0] == 1
        assert connection.execute("SELECT DISTINCT embedding_status FROM chunks").fetchone()[0] == "warning"


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


def test_embed_query_logs_warning_on_provider_failure(monkeypatch, caplog):
    class Broken(FakeProvider):
        def embed(self, texts):
            raise EmbeddingError("mock outage")

    monkeypatch.setattr(embedding_service_module, "resolve_embedding_provider", lambda: Broken())

    with caplog.at_level("WARNING", logger="service.core.embeddings.service"):
        result = embed_query("some query")

    assert result is None
    assert any("mock outage" in record.getMessage() for record in caplog.records)


def test_embedding_query_configuration_reports_disabled_without_provider_call(monkeypatch):
    monkeypatch.setattr(embedding_service_module, "get_setting", lambda key, default=None: "disabled" if key == "embedding_provider" else default)
    monkeypatch.setattr(
        embedding_service_module,
        "get_embedding_api_key",
        lambda: (_ for _ in ()).throw(AssertionError("disabled provider must not read credentials")),
    )

    status = embedding_query_configuration()

    assert status.available is False
    assert status.reason == "embedding_provider_unconfigured"


def test_embedding_query_configuration_fast_fails_unreachable_loopback_provider(monkeypatch):
    settings = {
        "embedding_provider": "openai_compatible",
        "embedding_base_url": "http://localhost:11434/v1",
        "embedding_model": "all-minilm",
    }
    monkeypatch.setattr(embedding_service_module, "get_setting", lambda key, default=None: settings.get(key, default))
    monkeypatch.setattr(embedding_service_module, "get_embedding_api_key", lambda: "local-key")
    monkeypatch.setattr(
        embedding_service_module.socket,
        "create_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("connection refused")),
    )

    status = embedding_query_configuration()

    assert status.available is False
    assert status.reason == "embedding_provider_endpoint_unreachable"


def test_embedding_query_configuration_rejects_malformed_base_url(monkeypatch):
    settings = {
        "embedding_provider": "openai_compatible",
        "embedding_base_url": "not-a-url",
        "embedding_model": "all-minilm",
    }
    monkeypatch.setattr(embedding_service_module, "get_setting", lambda key, default=None: settings.get(key, default))
    monkeypatch.setattr(embedding_service_module, "get_embedding_api_key", lambda: "local-key")

    status = embedding_query_configuration()

    assert status.available is False
    assert status.reason == "embedding_provider_invalid_configuration"


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
