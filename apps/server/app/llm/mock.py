"""离线 mock 后端：未配置 API key 时的兜底（本地零外发，符合红线 1 的最严格解读）。

真实路径（LLMClient）与 mock 路径实现同一 `chat` 接口；qa / knowledge 层通过
注入 responder 决定 mock 的生成逻辑（检索式回答 → 引用天然真实）。
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from typing import Any

from .types import ChatMessage, ChatResult, Role, UsageInfo

Responder = Callable[[list[ChatMessage], Role], str]


def _default_responder(messages: list[ChatMessage], role: Role) -> str:
    return "（离线模式：未配置模型 API key）"


class MockLLMClient:
    """确定性 mock：token 数按内容长度模拟，缓存命中按「相同前缀指纹」模拟。"""

    provider = "mock"
    model = "mock-offline"

    def __init__(self, usage_log, responder: Responder | None = None) -> None:
        self.usage_log = usage_log
        self.responder = responder or _default_responder
        self._prefix_seen: set[str] = set()
        self.calls: list[list[ChatMessage]] = []

    def _approx_tokens(self, text: str) -> int:
        # 中文字符≈1 token/字，ASCII≈0.3 token/字符 的粗略模拟
        cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
        other = len(text) - cjk
        return max(1, cjk + other // 3)

    def _prefix_fingerprint(self, messages: list[ChatMessage]) -> str:
        # 常驻上下文由首条（system）承载；相同指纹视为前缀缓存命中（T1.3.3）
        head = messages[0].content[:2048] if messages else ""
        return hashlib.sha256(head.encode("utf-8")).hexdigest()

    async def chat(
        self,
        role: Role,
        messages: list[ChatMessage],
        *,
        book_id: str | None = None,
        purpose: str = "",
        extra_body: dict[str, Any] | None = None,
    ) -> ChatResult:
        self.calls.append(list(messages))
        start = time.monotonic()
        content = self.responder(list(messages), role)
        prompt_tokens = sum(self._approx_tokens(m.content) for m in messages)
        completion_tokens = self._approx_tokens(content)

        fp = self._prefix_fingerprint(messages)
        # 重复前缀：90% 的输入 token 视为缓存命中（模拟服务商前缀缓存计费）
        cache_hit = int(prompt_tokens * 0.9) if fp in self._prefix_seen else 0
        self._prefix_seen.add(fp)

        usage = UsageInfo(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cache_hit_tokens=max(cache_hit, 0),
        )
        self.usage_log.record(
            role=role,
            provider=self.provider,
            model=self.model,
            usage=usage,
            duration_ms=int((time.monotonic() - start) * 1000),
            status="ok",
            book_id=book_id,
            purpose=purpose,
            extra={"mock": True},
        )
        return ChatResult(
            content=content, usage=usage, provider=self.provider, model=self.model
        )
