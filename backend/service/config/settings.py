"""
这个文件负责定义后端的运行时配置。
它在整个框架里扮演"环境配置"的角色：集中管理数据目录、CORS 白名单、SQLite 路径等运行参数。
"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class Paths(BaseModel):
    """所有本地数据目录的集中配置。"""

    data_dir: Path = Field(default_factory=lambda: Path.home() / ".repomind")
    database_path: Path = Field(default_factory=lambda: Path.home() / ".repomind" / "repomind.sqlite3")


class Settings(BaseSettings):
    """应用运行时配置。

    默认值设计为"开箱即用"：不需要额外配置就能在本机跑起来。
    """

    app_name: str = "RepoMind"
    app_version: str = "0.1.0"
    api_version: str = "v1"
    backend_contract_version: str = "1"
    instance_id: str = "repomind-desktop-backend"
    session_id: str | None = None
    # Electron 每次启动都会生成新的业务令牌；未配置时保持命令行开发和后端测试兼容。
    api_token: str | None = None
    # Electron 只在本机临时注入此令牌，用于请求后端优雅退出。
    shutdown_token: str | None = None
    # 桌面版注入启动后端的 Electron 主进程 PID；后端仅监视经直接父子关系验证的 PID。
    electron_parent_pid: int | None = Field(default=None, ge=1)
    port: int = Field(default=8000, ge=1, le=65535)
    api_base_url: str = "http://127.0.0.1:8000/api/v1"
    # Electron 打包页使用 Origin: null；Vite 开发页必须匹配包含端口的完整 Origin。
    cors_origins: list[str] = [
        "null",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    debug: bool = False
    paths: Paths = Field(default_factory=Paths)

    class Config:
        env_prefix = "REPOMIND_"
        env_nested_delimiter = "__"


_settings: Settings | None = None


def get_settings() -> Settings:
    """获取全局唯一的 Settings 单例。"""
    global _settings
    if _settings is None:
        _settings = Settings()
        _settings.paths.data_dir.mkdir(parents=True, exist_ok=True)
        _settings.paths.database_path.parent.mkdir(parents=True, exist_ok=True)
    return _settings
