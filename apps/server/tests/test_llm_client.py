"""统一模型客户端（计划 T1.1.1）：鉴权/超时/重试/错误归一化/计费落盘。"""

from __future__ import annotations

import httpx
import pytest
from app.llm.client import LLMClient
from app.llm.errors import ModelAuthError, ModelError, ModelRateLimitError
from app.llm.types import ChatMessage, UsageInfo
from app.llm.usage import UsageLog

PROVIDER = {
    "endpoint": "https://mock.example/v1",
    "api_key": "sk-test",
    "model": "test-chat",
    "price": {"input_per_m": 2.0, "output_per_m": 8.0, "cache_hit_per_m": 0.2},
    "timeout_s": 5,
}


def make_client(handler, usage_log) -> LLMClient:
    return LLMClient(
        "testprov",
        PROVIDER,
        usage_log,
        transport=httpx.MockTransport(handler),
    )


def ok_response(content: str = "回答内容") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"role": "assistant", "content": content}}],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "prompt_cache_hit_tokens": 60,
            },
        },
    )


@pytest.mark.asyncio
async def test_chat_success_with_usage_and_cost(storage) -> None:
    usage_log = UsageLog(storage)
    client = make_client(lambda req: ok_response("供需均衡"), usage_log)
    result = await client.chat("long_text_qa", [ChatMessage("user", "问题")], purpose="qa")
    assert result.content == "供需均衡"
    assert result.usage.prompt_tokens == 100
    assert result.usage.cache_hit_tokens == 60
    # 计费：60 命中×0.2 + 40 未命中×2.0 + 20 输出×8.0（每百万）≈ 0.000196
    entries = usage_log.read_all()
    assert len(entries) == 1
    assert entries[0]["status"] == "ok"
    expected_cost = 60 * 0.2 / 1e6 + 40 * 2.0 / 1e6 + 20 * 8.0 / 1e6
    assert entries[0]["costCny"] == pytest.approx(expected_cost, abs=1e-8)


@pytest.mark.asyncio
async def test_retry_on_5xx_then_success(storage) -> None:
    usage_log = UsageLog(storage)
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500, text="boom")
        return ok_response("重试成功")

    client = make_client(handler, usage_log)
    result = await client.chat("long_text_qa", [ChatMessage("user", "q")])
    assert result.content == "重试成功"
    assert calls["n"] == 2
    assert len(usage_log.read_all()) == 1  # 只记最终成功一次


@pytest.mark.asyncio
async def test_auth_error_not_retried(storage) -> None:
    usage_log = UsageLog(storage)
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(401, text="bad key")

    client = make_client(handler, usage_log)
    with pytest.raises(ModelAuthError):
        await client.chat("long_text_qa", [ChatMessage("user", "q")], session_id="s-fail")
    assert calls["n"] == 1  # 鉴权错误立即失败，不重试
    entry = usage_log.read_all()[0]
    assert entry["status"] == "error:auth"
    assert entry["sessionId"] == "s-fail"  # 评审 D11：失败调用也归入会话统计


@pytest.mark.asyncio
async def test_rate_limit_retried_then_raises(storage) -> None:
    usage_log = UsageLog(storage)
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(429, text="slow down")

    client = make_client(handler, usage_log)
    with pytest.raises(ModelRateLimitError):
        await client.chat("long_text_qa", [ChatMessage("user", "q")])
    assert calls["n"] == 3  # 1 + 2 次重试


@pytest.mark.asyncio
async def test_malformed_response_raises_provider_error(storage) -> None:
    usage_log = UsageLog(storage)
    client = make_client(lambda req: httpx.Response(200, json={"unexpected": True}), usage_log)
    with pytest.raises(ModelError) as ei:
        await client.chat("long_text_qa", [ChatMessage("user", "q")])
    assert ei.value.kind == "provider"


def test_usage_summary_and_cache_rate(storage) -> None:
    log = UsageLog(storage)
    log.register_price("p", {"input_per_m": 1.0, "output_per_m": 1.0, "cache_hit_per_m": 0.1})
    log.record(
        role="long_text_qa",
        provider="p",
        model="m",
        usage=UsageInfo(prompt_tokens=100, completion_tokens=50, cache_hit_tokens=40),
        duration_ms=10,
        status="ok",
        book_id="b1",
    )
    log.record(
        role="long_text_qa",
        provider="p",
        model="m",
        usage=UsageInfo(prompt_tokens=10, completion_tokens=0),
        duration_ms=5,
        status="error:timeout",
        book_id="b2",
    )
    summary_all = log.summary()
    assert summary_all["totalCalls"] == 2
    assert summary_all["okCalls"] == 1
    assert summary_all["cacheHitTokens"] == 40
    assert summary_all["cacheHitRate"] == pytest.approx(40 / 110, abs=5e-4)
    summary_book = log.summary(book_id="b1")
    assert summary_book["totalCalls"] == 1
