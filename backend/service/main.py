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
from service.config.settings import get_settings
from service.storage.sqlite_db import get_connection

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """创建 FastAPI 应用。"""
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/v1/health")
    def health() -> dict:
        """健康检查接口。"""
        return {
            "status": "ok",
            "app_name": settings.app_name,
            "database_path": str(settings.paths.database_path),
        }

    app.include_router(repos_router, prefix="/api/v1")
    app.include_router(analysis_router, prefix="/api/v1")
    app.include_router(collaborate_router, prefix="/api/v1")
    app.include_router(code_graph_router, prefix="")
    return app


app = create_app()


def main() -> None:
    """启动后端服务。"""
    import uvicorn

    settings = get_settings()
    get_connection()
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
