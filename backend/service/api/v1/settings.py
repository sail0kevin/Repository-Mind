"""
这个文件负责应用设置的读写接口。
它在整个框架里扮演"设置 API"的角色：非敏感配置写入 SQLite，API Key 只进入 SecretStore。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from service.core.redaction import redact_secret
from service.storage.models import SettingsResponse, SettingsUpdateRequest
from service.storage.secret_store import (
    SecretStore, SecretStoreUnavailableError, get_embedding_api_key, get_llm_api_key, get_secret_store,
)
from service.storage.settings_store import read_settings_dict, set_setting

router = APIRouter(tags=["settings"])
_LLM_SECRET_NAME = "llm_api_key"
_EMBEDDING_SECRET_NAME = "embedding_api_key"


def _read_api_key(secret_store: SecretStore) -> str | None:
    """先执行一次兼容迁移，再从安全存储读取密钥。"""

    return get_llm_api_key(secret_store)


@router.get("/settings", response_model=SettingsResponse)
def get_settings(secret_store: SecretStore = Depends(get_secret_store)) -> SettingsResponse:
    """读取设置；响应永远不包含 API Key 原文。"""

    current = read_settings_dict()
    try:
        api_key = _read_api_key(secret_store)
        embedding_api_key = get_embedding_api_key(secret_store)
    except SecretStoreUnavailableError:
        # 非敏感设置仍可读取；用户可通过 PUT clear/set 修复密钥存储。
        api_key = None
        embedding_api_key = None
    defaults = SettingsResponse()
    return SettingsResponse(
        api_base_url=current.get("api_base_url", defaults.api_base_url),
        llm_api_key_configured=bool(api_key),
        llm_api_key_hint=redact_secret(api_key),
        llm_base_url=current.get("llm_base_url", defaults.llm_base_url),
        llm_model=current.get("llm_model", defaults.llm_model),
        llm_temperature=current.get("llm_temperature", defaults.llm_temperature),
        llm_max_tokens=current.get("llm_max_tokens", defaults.llm_max_tokens),
        embedding_provider=current.get("embedding_provider", defaults.embedding_provider),
        embedding_api_key_configured=bool(embedding_api_key),
        embedding_api_key_hint=redact_secret(embedding_api_key),
        embedding_base_url=current.get("embedding_base_url", defaults.embedding_base_url),
        embedding_model=current.get("embedding_model", defaults.embedding_model),
        retrieval_limit=current.get("retrieval_limit", defaults.retrieval_limit),
        input_cost_per_1k_tokens=current.get("input_cost_per_1k_tokens", defaults.input_cost_per_1k_tokens),
        output_cost_per_1k_tokens=current.get("output_cost_per_1k_tokens", defaults.output_cost_per_1k_tokens),
    )


@router.put("/settings", response_model=SettingsResponse)
def update_settings(
    request: SettingsUpdateRequest,
    secret_store: SecretStore = Depends(get_secret_store),
) -> SettingsResponse:
    """更新设置，并按 unchanged/set/clear 契约处理 API Key。"""

    secret_update = request.secret_update()
    embedding_secret_update = request.embedding_secret_update()
    for name, update in (
        (_LLM_SECRET_NAME, secret_update),
        (_EMBEDDING_SECRET_NAME, embedding_secret_update),
    ):
        if update.action == "unchanged":
            try:
                secret_store.get(name)
            except SecretStoreUnavailableError:
                pass
        elif update.action == "set":
            # SecretUpdate 已在模型校验中保证 set 一定携带非空 value。
            assert update.value is not None
            secret_store.set(name, update.value.strip())
        elif update.action == "clear":
            secret_store.delete(name)

    # 排除全部新旧密钥字段，防止任何密钥重新落入 settings 表。
    values = request.model_dump(
        exclude_unset=True,
        exclude_none=True,
        exclude={"llm_api_key", "llm_api_key_update", "embedding_api_key", "embedding_api_key_update"},
    )
    for key, value in values.items():
        set_setting(key, value)
    return get_settings(secret_store)
