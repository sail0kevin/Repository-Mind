"""验证 M0 密钥安全、迁移和 settings API 契约。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# 让测试可以直接从 backend 目录导入 service 包。
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from service.config import settings as config_module
from service.config.settings import Paths, Settings
from service.core.llm_client import resolve_runtime_config
from service.core.redaction import redact_secret
from service.main import create_app
from service.storage.secret_store import MemorySecretStore, get_secret_store, set_secret_store
from service.storage.settings_store import get_setting, set_setting


@pytest.fixture()
def client_and_store(tmp_path: Path):
    """每个测试使用独立 SQLite 和内存密钥存储。"""

    original_settings = config_module._settings
    store = MemorySecretStore()
    config_module._settings = Settings(
        paths=Paths(
            data_dir=tmp_path,
            database_path=tmp_path / "test.sqlite3",
        )
    )
    set_secret_store(store)
    app = create_app()
    app.dependency_overrides[get_secret_store] = lambda: store
    try:
        with TestClient(app) as client:
            yield client, store
    finally:
        set_secret_store(None)
        config_module._settings = original_settings


def test_redact_secret_only_exposes_short_hint() -> None:
    """脱敏提示只能暴露末四位，短密钥完全遮挡。"""

    assert redact_secret(None) is None
    assert redact_secret("abc") == "•••"
    assert redact_secret("sk-secret-1234") == "••••1234"


def test_get_migrates_legacy_plaintext_and_never_echoes_key(client_and_store) -> None:
    """GET 会迁移旧明文，但响应 JSON 中不能出现原始密钥或旧字段。"""

    client, store = client_and_store
    set_setting("llm_api_key", "sk-legacy-9876")

    response = client.get("/api/v1/settings")

    assert response.status_code == 200
    payload = response.json()
    assert payload["llm_api_key_configured"] is True
    assert payload["llm_api_key_hint"] == "••••9876"
    assert "llm_api_key" not in payload
    assert "sk-legacy-9876" not in response.text
    assert store.get("llm_api_key") == "sk-legacy-9876"
    assert get_setting("llm_api_key") is None


def test_put_supports_set_unchanged_and_clear(client_and_store) -> None:
    """新契约的三个动作均可用，且响应从不泄露密钥。"""

    client, store = client_and_store
    set_response = client.put(
        "/api/v1/settings",
        json={"llm_api_key_update": {"action": "set", "value": "sk-new-4321"}},
    )
    assert set_response.status_code == 200
    assert store.get("llm_api_key") == "sk-new-4321"
    assert "sk-new-4321" not in set_response.text

    unchanged_response = client.put(
        "/api/v1/settings",
        json={"llm_api_key_update": {"action": "unchanged"}, "llm_model": "test-model"},
    )
    assert unchanged_response.status_code == 200
    assert unchanged_response.json()["llm_model"] == "test-model"
    assert store.get("llm_api_key") == "sk-new-4321"

    clear_response = client.put(
        "/api/v1/settings",
        json={"llm_api_key_update": {"action": "clear"}},
    )
    assert clear_response.status_code == 200
    assert clear_response.json()["llm_api_key_configured"] is False
    assert clear_response.json()["llm_api_key_hint"] is None
    assert store.get("llm_api_key") is None


def test_put_accepts_legacy_key_without_persisting_or_echoing_it(client_and_store) -> None:
    """旧 llm_api_key 请求仍可设置/清除，但不会再写回 settings 表。"""

    client, store = client_and_store
    response = client.put("/api/v1/settings", json={"llm_api_key": "sk-old-client-2468"})

    assert response.status_code == 200
    assert store.get("llm_api_key") == "sk-old-client-2468"
    assert get_setting("llm_api_key") is None
    assert "llm_api_key" not in response.json()
    assert "sk-old-client-2468" not in response.text

    clear_response = client.put("/api/v1/settings", json={"llm_api_key": ""})
    assert clear_response.status_code == 200
    assert store.get("llm_api_key") is None


def test_llm_client_reads_api_key_from_secret_store(client_and_store) -> None:
    """LLM 客户端只从 SecretStore 获取密钥，普通配置仍从 settings 表读取。"""

    _, store = client_and_store
    store.set("llm_api_key", "sk-runtime-1357")
    set_setting("llm_model", "runtime-model")

    runtime = resolve_runtime_config()

    assert runtime.api_key == "sk-runtime-1357"
    assert runtime.model == "runtime-model"


def test_migration_does_not_delete_plaintext_when_secret_save_fails(client_and_store) -> None:
    """安全保存失败时保留旧明文，避免迁移异常造成密钥永久丢失。"""

    client, _ = client_and_store

    class FailingSecretStore(MemorySecretStore):
        def set(self, name: str, value: str) -> None:
            raise OSError("fake secret store failure")

    set_setting("llm_api_key", "sk-retry-0000")
    client.app.dependency_overrides[get_secret_store] = lambda: FailingSecretStore()

    with pytest.raises(OSError):
        client.get("/api/v1/settings")
    assert get_setting("llm_api_key") == "sk-retry-0000"
