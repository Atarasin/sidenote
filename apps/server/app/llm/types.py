"""模型层公共类型（上游 §2.2 模型路由 / §3.6 成本闸门的数据载体）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# 路由角色（上游 §2.2 按能力分工）
Role = Literal[
    "long_text_qa",  # 长文理解/问答：Kimi 或 DeepSeek
    "vision",  # 截图理解（M3 用，本里程碑留路由位）：Kimi / GLM 视觉版
    "text_to_image",  # 文生图兜底（M2 用，选型已登记）
    "embedding",  # 旁证检索向量化（本地实现，不走外部服务）
]


@dataclass
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass
class UsageInfo:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    # 服务商上下文缓存命中（DeepSeek: prompt_cache_hit_tokens；mock 模拟）。
    # 上游红线：重复前缀只计费一次 → 命中部分按缓存价计（见 usage.py 价格表）。
    cache_hit_tokens: int = 0


@dataclass
class ChatResult:
    content: str
    usage: UsageInfo = field(default_factory=UsageInfo)
    provider: str = ""
    model: str = ""
    raw: dict[str, Any] = field(default_factory=dict)
