"""
这个文件负责启动 FastAPI 后端服务。
它在整个框架里扮演"后端入口"的角色：挂载路由、配置 CORS、初始化存储，并提供健康检查接口。
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from service.api.v1.repos import analysis_router, router as repos_router
from service.api.v1.collaborate import router as collaborate_router
from service.api.v1.code_graph import router as code_graph_router
from service.api.v1.jobs import router as jobs_router
from service.api.v1.settings import router as settings_router
from service.config.settings import get_settings
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
    async def allow_options_preflight(request, call_next):
        """让所有 OPTIONS 预检请求直接返回 200，避免桌面端 Fast Refresh 的 OPTIONS 探测被路由层拒绝。"""
        if request.method == "OPTIONS":
            from fastapi.responses import Response
            return Response(status_code=200)
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

    @app.get("/api/v1/health", response_model=HealthResponse)
    def health() -> dict:
        """返回桌面端可校验的身份、运行会话和数据库真实版本。"""
        with get_connection() as connection:
            database_schema_version = get_database_schema_version(connection)
        supported_schema_version = get_latest_schema_version()
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
            "database_path": str(settings.paths.database_path.resolve()),
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
    """启动后端服务。"""
    import uvicorn

    settings = get_settings()
    uvicorn.run(app, host="127.0.0.1", port=settings.port)


if __name__ == "__main__":
    main()
