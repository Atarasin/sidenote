"""模型路由（计划 T1.1.2）：角色解析、无 key 降级 mock、有 key 走真实客户端。"""

from __future__ import annotations

from app.llm import router
from app.llm.client import LLMClient
from app.llm.mock import MockLLMClient
from app.llm.usage import UsageLog


def test_default_routing_roles() -> None:
    assert router.resolve_role_provider("long_text_qa") == "deepseek"
    assert router.resolve_role_provider("vision") == "glm_vision"
    assert router.resolve_role_provider("text_to_image") == "cogview"


def test_no_key_falls_back_to_mock(storage, monkeypatch) -> None:
    monkeypatch.setattr(
        router, "load_config", lambda: {"models": {"routing": {}, "providers": {}}}
    )
    usage_log = UsageLog(storage)
    backend = router.get_backend("long_text_qa", usage_log)
    assert isinstance(backend, MockLLMClient)


def test_with_key_returns_real_client(storage, monkeypatch) -> None:
    cfg = {
        "models": {
            "routing": {"long_text_qa": "kimi"},
            "providers": {
                "kimi": {
                    "endpoint": "https://api.moonshot.cn/v1",
                    "api_key": "sk-local",
                    "model": "moonshot-v1-32k",
                    "price": {"input_per_m": 24.0, "output_per_m": 24.0, "cache_hit_per_m": 6.0},
                }
            },
        }
    }
    monkeypatch.setattr(router, "load_config", lambda: cfg)
    usage_log = UsageLog(storage)
    backend = router.get_backend("long_text_qa", usage_log)
    assert isinstance(backend, LLMClient)
    assert backend.provider == "kimi"
    # 价格已注册进计费（百万输入 token ≈ 24 元）
    from app.llm.types import UsageInfo

    assert usage_log.estimate_cost_cny("kimi", UsageInfo(prompt_tokens=1_000_000)) == 24.0


def test_mock_backend_usage_logged(storage) -> None:
    import asyncio

    from app.llm.types import ChatMessage

    usage_log = UsageLog(storage)
    mock = MockLLMClient(usage_log, responder=lambda msgs, role: "离线回答")
    result = asyncio.run(
        mock.chat(
            "long_text_qa",
            [ChatMessage("system", "常驻"), ChatMessage("user", "问")],
            book_id="b",
            purpose="qa",
        )
    )
    assert result.content == "离线回答"
    assert result.provider == "mock"
    entries = usage_log.read_all()
    assert entries[0]["mock"] is True
    assert entries[0]["bookId"] == "b"

    # 第二次相同前缀 → 模拟缓存命中
    asyncio.run(
        mock.chat("long_text_qa", [ChatMessage("system", "常驻"), ChatMessage("user", "问2")])
    )
    assert usage_log.read_all()[-1]["cacheHitTokens"] > 0
