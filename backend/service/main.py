"""
这个文件负责启动 FastAPI 后端服务。
它在整个框架里扮演"后端入口"的角色：挂载路由、配置 CORS、初始化存储，并提供健康检查接口。
"""
from __future__ import annotations

from service.core.database_identity import compute_database_identity
import logging
import secrets

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from service.api.v1.repos import analysis_router, router as repos_router
from service.api.v1.collaborate import router as collaborate_router
from service.api.v1.code_graph import router as code_graph_router
from service.api.v1.jobs import router as jobs_router
from service.api.v1.settings import router as settings_router
from service.config.settings import get_settings
from service.core.parent_watchdog import start_parent_lifetime_watchdog
from service.storage.job_store import recover_interrupted_jobs
from service.storage.models import HealthResponse
from service.storage.snapshot_store import recover_building_snapshots
from service.storage.sqlite_db import get_connection
from service.storage.migrations.runner import (
    get_database_schema_version,
    get_latest_schema_version,
)

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """创建 FastAPI 应用。"""
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version=settings.app_version)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def verify_desktop_api_token(request: Request, call_next):
        """Electron 模式下保护业务接口；健康检查和优雅退出保留各自的独立契约。"""
        public_paths = {"/api/v1/health", "/api/v1/runtime/shutdown"}
        # CORS 预检不携带业务令牌，必须交给外层 CORSMiddleware 生成允许头；
        # 实际 GET/POST 等业务方法仍在下面执行令牌校验。
        if request.method == "OPTIONS":
            return await call_next(request)
        if settings.api_token and request.url.path not in public_paths:
            supplied_token = request.headers.get("X-RepoMind-API-Token")
            if not supplied_token or not secrets.compare_digest(supplied_token, settings.api_token):
                # 使用 404 减少向本机其他网页暴露服务身份和认证细节。
                return JSONResponse(status_code=404, content={"detail": "Not found"})
        return await call_next(request)

    @app.on_event("startup")
    def initialize_runtime() -> None:
        """初始化数据库，并把上次进程遗留的 running 任务标记为 interrupted。"""
        with get_connection():
            pass
        recovered = recover_interrupted_jobs()
        recovered_snapshots = recover_building_snapshots()
        if recovered:
            logger.warning("已恢复 %d 个中断任务。", recovered)
        if recovered_snapshots:
            logger.warning("已恢复 %d 个中断快照。", recovered_snapshots)

    @app.post("/api/v1/runtime/shutdown", status_code=202)
    def shutdown(x_repomind_shutdown_token: str | None = Header(default=None)) -> dict[str, str]:
        """仅允许当前 Electron 会话请求后端优雅退出。"""
        if not settings.shutdown_token or x_repomind_shutdown_token != settings.shutdown_token:
            raise HTTPException(status_code=404, detail="Not found")

        import threading

        def stop_server() -> None:
            import os

            os._exit(0)

        threading.Timer(0.05, stop_server).start()
        return {"status": "stopping"}

    @app.get("/api/v1/health", response_model=HealthResponse)
    def health() -> dict:
        """返回桌面端可校验的身份、运行会话和数据库真实版本。"""
        with get_connection() as connection:
            database_schema_version = get_database_schema_version(connection)
        supported_schema_version = get_latest_schema_version()
        database_identity = compute_database_identity(settings.paths.database_path)
        return {
            "status": "ok",
            "app_name": settings.app_name,
            "app_version": settings.app_version,
            "api_version": settings.api_version,
            # 保留旧 schema_version 字段，并把语义固定为数据库实际版本。
            "schema_version": database_schema_version,
            "supported_schema_version": supported_schema_version,
            "database_schema_version": database_schema_version,
            "backend_contract_version": settings.backend_contract_version,
            "instance_id": settings.instance_id,
            "session_id": settings.session_id,
            # 公共健康检查只返回稳定指纹，避免向同机未认证网页暴露绝对路径。
            "database_identity": database_identity,
        }

    app.include_router(repos_router, prefix="/api/v1")
    app.include_router(analysis_router, prefix="/api/v1")
    app.include_router(collaborate_router, prefix="/api/v1")
    app.include_router(jobs_router, prefix="/api/v1")
    app.include_router(settings_router, prefix="/api/v1")
    app.include_router(code_graph_router, prefix="")
    return app


app = create_app()


def main() -> None:
    """按命令行模式启动 FastAPI，或把同一冻结程序作为只读 stdio MCP Server。"""
    import sys

    if "--mcp" in sys.argv[1:]:
        from service.mcp_server.__main__ import main as run_mcp_server

        run_mcp_server()
        return

    import uvicorn

    settings = get_settings()
    start_parent_lifetime_watchdog(settings.electron_parent_pid)
    uvicorn.run(app, host="127.0.0.1", port=settings.port)


if __name__ == "__main__":
    main()
