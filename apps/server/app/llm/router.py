"""模型路由（计划 T1.1.2 / 上游 §2.2）：角色 → 提供方，未配置 key 时降级 mock。

选型登记（上游文档 §9）：
- long_text_qa：DeepSeek（低成本，默认）/ Kimi（长上下文，可切换）
- vision：GLM 视觉版 / Kimi 视觉版（M3 使用，本里程碑只留路由位）
- text_to_image：智谱 CogView（M2 使用）
- embedding：本地字符 n-gram TF-IDF（零外发、零成本；见 knowledge/retrieval.py）
"""

from __future__ import annotations

from typing import Any

from ..config import load_config
from .client import LLMClient
from .mock import MockLLMClient
from .types import Role
from .usage import UsageLog

# 角色默认提供方（config.models.routing 可覆盖）
DEFAULT_ROUTING: dict[str, str] = {
    "long_text_qa": "deepseek",
    "vision": "glm_vision",
    "text_to_image": "cogview",
}


def resolve_role_provider(role: Role | str) -> str:
    routing = load_config().get("models", {}).get("routing", {})
    return str(routing.get(str(role), DEFAULT_ROUTING.get(str(role), "")))


def get_backend(
    role: Role,
    usage_log: UsageLog,
    *,
    mock_client: MockLLMClient | None = None,
) -> Any:
    """解析角色的可用后端：配置了 key → LLMClient；否则 mock。

    任何调用方拿到的都是带 `chat(role, messages, ...)` 的对象。
    """
    models_cfg = load_config().get("models", {})
    provider_name = resolve_role_provider(role)
    provider_cfg = (models_cfg.get("providers", {}) or {}).get(provider_name)
    if provider_name and provider_cfg and provider_cfg.get("api_key"):
        # 价格表注册进计费
        if provider_cfg.get("price"):
            usage_log.register_price(provider_name, provider_cfg["price"])
        return LLMClient(provider_name, dict(provider_cfg), usage_log)
    return mock_client if mock_client is not None else MockLLMClient(usage_log)
