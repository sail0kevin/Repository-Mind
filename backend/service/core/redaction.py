"""
这个文件提供日志和界面提示需要的密钥脱敏工具。
任何调用方都只能获得提示文本，不能从提示反推出完整密钥。
"""
from __future__ import annotations


def redact_secret(value: str | None) -> str | None:
    """把密钥缩略为不可用于认证的提示；未配置时返回 None。"""

    if not value:
        return None
    if len(value) <= 4:
        return "•" * len(value)
    return f"••••{value[-4:]}"
