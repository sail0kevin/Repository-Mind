"""
这个文件负责应用设置的持久化读写。
它在整个框架里扮演"配置持久层"的角色：只保存 Base URL、模型名等非敏感设置，API Key 由 SecretStore 单独管理。
"""
from __future__ import annotations

import json
from typing import Any

from service.storage.sqlite_db import get_connection


def get_setting(key: str, default: Any = None) -> Any:
    """读取单个配置项。"""
    with get_connection() as connection:
        row = connection.execute(
            "SELECT value FROM settings WHERE key = ?",
            (key,),
        ).fetchone()
    if row is None or row["value"] is None:
        return default
    return json.loads(row["value"])


def set_setting(key: str, value: Any) -> None:
    """写入或覆盖单个配置项。"""
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = CURRENT_TIMESTAMP
            """,
            (key, json.dumps(value, ensure_ascii=False)),
        )


def delete_setting(key: str) -> None:
    """删除单个配置项，供明文密钥迁移和清除操作使用。"""
    with get_connection() as connection:
        connection.execute("DELETE FROM settings WHERE key = ?", (key,))


def read_settings_dict() -> dict[str, Any]:
    """读取全部非敏感配置项，返回字典。"""
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT key, value FROM settings WHERE key != ?",
            ("llm_api_key",),
        ).fetchall()
    payload: dict[str, Any] = {}
    for row in rows:
        if row["value"] is None:
            continue
        payload[row["key"]] = json.loads(row["value"])
    return payload
