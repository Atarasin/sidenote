"""统一模型客户端（计划 T1.1.1）：OpenAI 兼容 chat/completions。

- 鉴权：API key 只从本地 config.local.yaml 读取（不入库）。
- 超时：每角色可配，默认 120s。
- 重试：可重试错误（超时/限流/网络/5xx）指数退避重试 2 次。
- 错误归一化：见 errors.from_http_status。
- 计费：每次调用（含失败）写 usage 日志（calls.jsonl），见 usage.py。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from .errors import ModelError, ModelNetworkError, ModelTimeoutError, from_http_status
from .types import ChatMessage, ChatResult, Role, UsageInfo
from .usage import UsageLog

_RETRYABLE_KINDS = {"timeout", "rate_limit", "network", "provider_5xx"}
_MAX_RETRIES = 2


class LLMClient:
    """OpenAI 兼容端点的统一异步客户端。provider_config 形如：

    { endpoint: "https://api.deepseek.com/v1", api_key: "sk-...", model: "deepseek-chat",
      price: {input_per_m: 1.0, output_per_m: 2.0, cache_hit_per_m: 0.1}, timeout_s: 120 }
    """

    def __init__(
        self,
        provider_name: str,
        provider_config: dict[str, Any],
        usage_log: UsageLog,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.provider = provider_name
        self.config = provider_config
        self.usage_log = usage_log
        self._transport = transport  # 测试注入
        if provider_config.get("price"):
            usage_log.register_price(provider_name, provider_config["price"])

    async def chat(
        self,
        role: Role,
        messages: list[ChatMessage],
        *,
        book_id: str | None = None,
        purpose: str = "",
        session_id: str = "",
        extra_body: dict[str, Any] | None = None,
    ) -> ChatResult:
        model = self.config["model"]
        endpoint = self.config["endpoint"].rstrip("/")
        api_key = self.config.get("api_key") or ""
        timeout_s = float(self.config.get("timeout_s", 120))

        body: dict[str, Any] = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        if extra_body:
            body.update(extra_body)

        last_error: ModelError | None = None
        for attempt in range(_MAX_RETRIES + 1):
            start = time.monotonic()
            try:
                async with httpx.AsyncClient(
                    timeout=timeout_s, transport=self._transport
                ) as client:
                    resp = await client.post(
                        f"{endpoint}/chat/completions",
                        headers={"Authorization": f"Bearer {api_key}"},
                        json=body,
                    )
                if resp.status_code != 200:
                    raise from_http_status(resp.status_code, resp.text)
                data = resp.json()
                result = self._parse_response(data, model)
                self.usage_log.record(
                    role=role,
                    provider=self.provider,
                    model=model,
                    usage=result.usage,
                    duration_ms=int((time.monotonic() - start) * 1000),
                    status="ok",
                    book_id=book_id,
                    purpose=purpose,
                    extra={"sessionId": session_id} if session_id else None,
                )
                return result
            except ModelError as exc:
                last_error = exc
                if exc.kind not in _RETRYABLE_KINDS or attempt == _MAX_RETRIES:
                    break
                await asyncio.sleep(0.5 * (2**attempt))
            except httpx.TimeoutException as exc:
                last_error = ModelTimeoutError(str(exc))
                if attempt == _MAX_RETRIES:
                    break
                await asyncio.sleep(0.5 * (2**attempt))
            except httpx.HTTPError as exc:
                last_error = ModelNetworkError(str(exc))
                if attempt == _MAX_RETRIES:
                    break
                await asyncio.sleep(0.5 * (2**attempt))

        assert last_error is not None
        self.usage_log.record(
            role=role,
            provider=self.provider,
            model=model,
            usage=UsageInfo(),
            duration_ms=0,
            status=f"error:{last_error.kind}",
            book_id=book_id,
            purpose=purpose,
            extra={"sessionId": session_id} if session_id else None,  # 失败调用也归入会话统计
        )
        raise last_error

    def _parse_response(self, data: dict[str, Any], model: str) -> ChatResult:
        try:
            content = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelError("provider", f"响应结构异常：{data}") from exc
        usage_raw = data.get("usage") or {}
        usage = UsageInfo(
            prompt_tokens=int(usage_raw.get("prompt_tokens", 0)),
            completion_tokens=int(usage_raw.get("completion_tokens", 0)),
            cache_hit_tokens=int(
                usage_raw.get("prompt_cache_hit_tokens", 0)  # DeepSeek 风格
                or usage_raw.get("cached_tokens", 0)  # 通用兼容
            ),
        )
        return ChatResult(content=content, usage=usage, provider=self.provider, model=model)
