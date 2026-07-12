"""
这个文件负责应用设置的读写接口。
它在整个框架里扮演"设置 API"的角色：让前端可以保存/读取 LLM 配置、单价、检索上限等运行时参数。
"""
from __future__ import annotations

from fastapi import APIRouter

from service.storage.models import SettingsResponse, SettingsUpdateRequest
from service.storage.settings_store import read_settings_dict, set_setting

router = APIRouter(tags=["settings"])


@router.get("/settings", response_model=SettingsResponse)
def get_settings() -> SettingsResponse:
    """读取当前全部设置。"""
    current = read_settings_dict()
    return SettingsResponse(
        api_base_url=current.get("api_base_url", SettingsResponse().api_base_url),
        llm_api_key=current.get("llm_api_key", ""),
        llm_base_url=current.get("llm_base_url", SettingsResponse().llm_base_url),
        llm_model=current.get("llm_model", SettingsResponse().llm_model),
        llm_temperature=current.get("llm_temperature", SettingsResponse().llm_temperature),
        llm_max_tokens=current.get("llm_max_tokens", SettingsResponse().llm_max_tokens),
        embedding_model=current.get("embedding_model", SettingsResponse().embedding_model),
        retrieval_limit=current.get("retrieval_limit", SettingsResponse().retrieval_limit),
        input_cost_per_1k_tokens=current.get("input_cost_per_1k_tokens", SettingsResponse().input_cost_per_1k_tokens),
        output_cost_per_1k_tokens=current.get("output_cost_per_1k_tokens", SettingsResponse().output_cost_per_1k_tokens),
    )


@router.put("/settings", response_model=SettingsResponse)
def update_settings(request: SettingsUpdateRequest) -> SettingsResponse:
    """更新设置，只覆盖用户显式传入的字段。"""
    for key, value in request.model_dump(exclude_unset=True).items():
        set_setting(key, value)
    return get_settings()
