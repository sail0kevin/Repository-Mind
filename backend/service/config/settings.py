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
    port: int = Field(default=8000, ge=1, le=65535)
    api_base_url: str = "http://127.0.0.1:8000/api/v1"
    cors_origins: list[str] = ["null", "http://localhost", "http://127.0.0.1"]
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
