"""
这个文件负责保存 API Key 等敏感信息。
它把业务代码与 Windows DPAPI 解耦，测试时可以注入纯内存实现，避免触碰真实系统密钥。
"""
from __future__ import annotations

import base64
import ctypes
import json
import os
import sys
from abc import ABC, abstractmethod
from ctypes import wintypes
from pathlib import Path
from threading import RLock

from service.config.settings import get_settings


class SecretStoreUnavailableError(RuntimeError):
    """密钥文件损坏、平台不支持或 DPAPI 解密失败时的结构化不可用错误。"""


class SecretStore(ABC):
    """敏感信息存储的统一接口。"""

    @abstractmethod
    def get(self, name: str) -> str | None:
        """读取密钥；不存在时返回 None。"""

    @abstractmethod
    def set(self, name: str, value: str) -> None:
        """安全保存密钥。"""

    @abstractmethod
    def delete(self, name: str) -> None:
        """删除密钥；不存在时也不报错。"""


class MemorySecretStore(SecretStore):
    """供单元测试和本地 Fake 场景使用的内存密钥存储。"""

    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self._values = dict(initial or {})

    def get(self, name: str) -> str | None:
        return self._values.get(name)

    def set(self, name: str, value: str) -> None:
        self._values[name] = value

    def delete(self, name: str) -> None:
        self._values.pop(name, None)


class _DataBlob(ctypes.Structure):
    """Windows CryptProtectData 使用的二进制缓冲区结构。"""

    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob_from_bytes(value: bytes) -> tuple[_DataBlob, ctypes.Array]:
    """把 Python bytes 转为 DPAPI 能读取的内存块，并保留缓冲区引用。"""

    buffer = ctypes.create_string_buffer(value)
    blob = _DataBlob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    return blob, buffer


def _dpapi_protect(value: bytes) -> bytes:
    """使用当前 Windows 用户凭据加密数据。"""

    if sys.platform != "win32":
        raise RuntimeError("DPAPI 密钥存储只能在 Windows 上使用。")
    input_blob, input_buffer = _blob_from_bytes(value)
    output_blob = _DataBlob()
    # input_buffer 必须活到系统调用结束，所以即使变量看似未使用也不能删除。
    _ = input_buffer
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(input_blob), None, None, None, None, 0, ctypes.byref(output_blob)
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output_blob.pbData)


def _dpapi_unprotect(value: bytes) -> bytes:
    """使用当前 Windows 用户凭据解密数据。"""

    if sys.platform != "win32":
        raise RuntimeError("DPAPI 密钥存储只能在 Windows 上使用。")
    input_blob, input_buffer = _blob_from_bytes(value)
    output_blob = _DataBlob()
    _ = input_buffer
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(input_blob), None, None, None, None, 0, ctypes.byref(output_blob)
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output_blob.pbData)


class WindowsDPAPISecretStore(SecretStore):
    """用 Windows DPAPI 加密后，将密文保存到应用数据目录。"""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or (get_settings().paths.data_dir / "secrets.json")
        self._lock = RLock()

    def _read_payload(self) -> dict[str, str]:
        """读取只包含 DPAPI 密文的 JSON 文件。"""

        if not self._path.exists():
            return {}
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SecretStoreUnavailableError("密钥存储文件不可读取或已损坏，可清除或重新设置 API Key 恢复。") from exc
        if not isinstance(payload, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in payload.items()):
            raise SecretStoreUnavailableError("密钥存储文件结构无效，可清除或重新设置 API Key 恢复。")
        return payload

    def _write_payload(self, payload: dict[str, str]) -> None:
        """用临时文件原子替换，避免程序中断留下半份密钥文件。"""

        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self._path.with_suffix(self._path.suffix + ".tmp")
        temporary_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary_path, self._path)

    def get(self, name: str) -> str | None:
        with self._lock:
            encoded = self._read_payload().get(name)
            if encoded is None:
                return None
            try:
                return _dpapi_unprotect(base64.b64decode(encoded, validate=True)).decode("utf-8")
            except (ValueError, UnicodeError, OSError, RuntimeError) as exc:
                raise SecretStoreUnavailableError("API Key 密文不可解密，可清除或重新设置后恢复。") from exc

    def set(self, name: str, value: str) -> None:
        with self._lock:
            try:
                payload = self._read_payload()
            except SecretStoreUnavailableError:
                # 保留损坏原文件供排查，写入全新有效文件即可恢复后续设置读取。
                payload = {}
            encrypted = _dpapi_protect(value.encode("utf-8"))
            payload[name] = base64.b64encode(encrypted).decode("ascii")
            self._write_payload(payload)

    def delete(self, name: str) -> None:
        with self._lock:
            try:
                payload = self._read_payload()
            except SecretStoreUnavailableError:
                # clear 是恢复动作：删除损坏文件，但不覆盖为伪造的空密文。
                if self._path.exists():
                    self._path.unlink()
                return
            if payload.pop(name, None) is not None:
                self._write_payload(payload)


_secret_store: SecretStore | None = None


def get_secret_store() -> SecretStore:
    """获取进程内唯一的生产密钥存储实例。"""

    global _secret_store
    if _secret_store is None:
        _secret_store = WindowsDPAPISecretStore()
    return _secret_store


def set_secret_store(store: SecretStore | None) -> None:
    """注入测试存储；传入 None 可恢复生产实现的延迟创建。"""

    global _secret_store
    _secret_store = store


def get_llm_api_key(store: SecretStore | None = None) -> str | None:
    """迁移旧 SQLite 明文后，从安全存储读取 LLM API Key。"""

    # 延迟导入可避免 sqlite_db 初始化时产生模块循环依赖。
    from service.storage.settings_store import delete_setting, get_setting

    effective_store = store or get_secret_store()
    legacy_value = get_setting("llm_api_key")
    if legacy_value is not None:
        # 已有 DPAPI 值优先，避免残留的旧 SQLite 明文覆盖用户后来更新的密钥。
        existing_value = effective_store.get("llm_api_key")
        if existing_value is None and isinstance(legacy_value, str) and legacy_value:
            effective_store.set("llm_api_key", legacy_value)
            if effective_store.get("llm_api_key") != legacy_value:
                raise RuntimeError("API Key 未能写入安全存储，已保留旧设置等待重试。")
        delete_setting("llm_api_key")
    return effective_store.get("llm_api_key")


def get_embedding_api_key(store: SecretStore | None = None) -> str | None:
    """读取独立的 Embedding API Key，绝不回退或复用 Chat 密钥。"""

    return (store or get_secret_store()).get("embedding_api_key")
