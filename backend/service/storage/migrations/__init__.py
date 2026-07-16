"""
这个包集中保存 SQLite 数据库迁移。
每个迁移都有固定版本和校验和，已经发布的迁移内容不能被静默修改。
"""

from service.storage.migrations.runner import run_migrations

__all__ = ["run_migrations"]
