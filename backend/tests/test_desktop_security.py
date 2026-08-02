"""桌面安全契约测试：聚焦 API 会话令牌，不启动真实 Electron。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from service.config import settings as settings_module
from service.config.settings import Paths, Settings
import service.main as main_module
from service.main import create_app


def test_loopback_is_the_default_and_remote_binding_requires_a_token():
    assert Settings().bind_host == "127.0.0.1"
    assert Settings(bind_host="localhost").api_token is None
    assert Settings(bind_host="::1").bind_host == "::1"

    with pytest.raises(ValueError, match="非 loopback"):
        Settings(bind_host="0.0.0.0")


def test_remote_binding_with_token_protects_business_api(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(
        settings_module,
        "_settings",
        Settings(
            bind_host="0.0.0.0",
            api_token="remote-api-token",
            paths=Paths(data_dir=data_dir, database_path=data_dir / "repomind.sqlite3"),
        ),
    )
    client = TestClient(create_app())

    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/repos").status_code == 404
    assert client.get(
        "/api/v1/repos",
        headers={"X-RepoMind-API-Token": "remote-api-token"},
    ).status_code == 200


def test_server_start_uses_configured_bind_host(monkeypatch):
    calls = {}
    monkeypatch.setattr(
        settings_module,
        "_settings",
        Settings(bind_host="0.0.0.0", api_token="remote-api-token"),
    )
    monkeypatch.setattr(main_module, "start_parent_lifetime_watchdog", lambda _pid: None)

    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: calls.update(kwargs))
    main_module.main()

    assert calls["host"] == "0.0.0.0"
    assert calls["port"] == 8000


def test_business_api_requires_electron_token_but_health_stays_public(tmp_path, monkeypatch):
    """配置令牌后，业务接口必须认证；健康检查仍可用于启动探测。"""
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(
        settings_module,
        "_settings",
        Settings(
            api_token="desktop-api-token",
            shutdown_token="shutdown-token",
            paths=Paths(data_dir=data_dir, database_path=data_dir / "repomind.sqlite3"),
        ),
    )
    client = TestClient(create_app())

    assert client.get("/api/v1/health").status_code == 200
    health_body = client.get("/api/v1/health").json()
    assert "database_path" not in health_body
    assert len(health_body["database_identity"]) == 64
    assert client.get("/api/v1/repos").status_code == 404
    assert client.get(
        "/api/v1/repos",
        headers={"X-RepoMind-API-Token": "wrong-token"},
    ).status_code == 404
    assert client.get(
        "/api/v1/repos",
        headers={"X-RepoMind-API-Token": "desktop-api-token"},
    ).status_code == 200


def test_cors_preflight_bypasses_business_token_middleware(tmp_path, monkeypatch):
    """带业务 token 的 CORS 预检不应被认证中间件拦截。"""
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(settings_module, "_settings", Settings(
        api_token="desktop-api-token",
        paths=Paths(data_dir=data_dir, database_path=data_dir / "repomind.sqlite3"),
        cors_origins=["http://localhost:5173"],
    ))
    with TestClient(create_app()) as client:
        response = client.options(
            "/api/v1/repos",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "X-RepoMind-API-Token",
            },
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "X-RepoMind-API-Token".lower() in response.headers["access-control-allow-headers"].lower()


def test_unconfigured_token_keeps_backend_development_compatible():
    """未配置令牌时保留纯后端开发和原有测试的无认证行为。"""
    client = TestClient(create_app())

    assert client.get("/api/v1/repos").status_code == 200
