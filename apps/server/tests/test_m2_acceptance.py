"""M2 验收（计划 Slice 2.7 / 上游 §6-M2）。

- T2.7.1：10 个真实晦涩概念生成图解（mock 确定性组件；人工评审「确实帮助理解」≥7/10
  属用户侧清单——见缺陷清单文档，真实模型配置后按同一清单复验）。
- T2.7.2：失败注入测试——动画生成失败场景 100% 有降级输出。
- T2.7.3：缓存测试——同一概念二次请求 100% 命中缓存、零新增生成调用。
"""

from __future__ import annotations

import pytest
from app.diagrams import service as diagram_service
from app.diagrams.rates import RateLimiter
from app.knowledge import mock_behaviors
from app.llm.mock import MockLLMClient
from app.llm.usage import UsageLog
from app.qa.service import validate_citations

CONCEPTS_10 = [
    "供需曲线",
    "均衡价格",
    "需求价格弹性",
    "机会成本",
    "生产可能性边界",
    "边际效用递减",
    "外部性",
    "公共物品",
    "信息不对称",
    "通货膨胀",
]


def _make_book(storage):
    from app.books.models import BookDoc, Chapter, DocMeta, Para, make_para_id

    paras = [
        f"{c}的图示与解释段落：{c}描述了经济中的一种基本关系，其图形与坐标轴交点有明确含义。"
        for c in CONCEPTS_10
    ]
    doc = BookDoc(
        meta=DocMeta(bookId="c" * 16, title="图解验收书", format="epub", fileHash="c" * 64),
        chapters=[
            Chapter(
                id="c001",
                title="第一章 概念图解",
                paras=[Para(id=make_para_id(1, i), text=t) for i, t in enumerate(paras, 1)],
            )
        ],
    )
    storage.write_bookdoc(doc)
    return doc


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    from app.storage import Storage

    storage = Storage(tmp_path_factory.mktemp("m2"))
    storage.ensure_layout()
    doc = _make_book(storage)
    usage_log = UsageLog(storage)
    backend = MockLLMClient(usage_log, responder=mock_behaviors.dispatch)
    limiter = RateLimiter(storage, limit=50, window_seconds=3600)
    return storage, usage_log, backend, limiter, doc


# ---------- T2.7.1：10 个概念生成图解 ----------


@pytest.mark.asyncio
async def test_10_concepts_generate_valid_diagrams(env) -> None:
    storage, _usage, backend, limiter, doc = env
    ok = 0
    for i, concept in enumerate(CONCEPTS_10):
        para_id = f"c001-p{i + 1:04d}"
        result = await diagram_service.generate_diagram(
            storage, backend, doc.meta.bookId, para_id, concept, limiter=limiter, session_id="acc"
        )
        assert result.kind == "interactive", f"{concept} 应生成交互组件（得到 {result.kind}）"
        # UI §3.4 双容器配色约束 + 沙箱检测约定
        assert "currentColor" in result.componentHtml
        assert "background:transparent" in result.componentHtml
        assert "sidenote:ready" in result.componentHtml
        # 红线 2：引用真实
        assert result.citations, f"{concept} 图解必须带引用"
        assert validate_citations(
            doc, [{"paraId": c.paraId, "quote": c.quote} for c in result.citations]
        )
        assert result.summary
        ok += 1
    assert ok == 10


# ---------- T2.7.2：失败注入 → 100% 降级 ----------


class _FailBackend:
    """注入：返回无法产出组件的垃圾内容（模拟动画生成失败）。"""

    provider = "failinject"

    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, role, messages, **kwargs):
        self.calls += 1
        content = "这不是 JSON，也没有组件。"
        return type("R", (), {"content": content})()


@pytest.mark.asyncio
async def test_failure_injection_always_degrades(tmp_path) -> None:
    from app.storage import Storage

    storage = Storage(tmp_path)
    storage.ensure_layout()
    doc = _make_book(storage)
    usage_log = UsageLog(storage)
    good = MockLLMClient(usage_log, responder=mock_behaviors.dispatch)
    fail = _FailBackend()
    limiter = RateLimiter(storage, limit=50)

    degraded_count = 0
    scenarios = ["空渲染", "脚本错误", "渲染超时", "组件缺失", "JSON 解析失败"]
    for i, scenario in enumerate(scenarios):
        para_id = f"c001-p{i + 1:04d}"
        concept = f"失败概念{i}"
        # 首答 + 修复重试都失败（注入后端）
        for repair in (False, True):
            await diagram_service.generate_diagram(
                storage,
                fail,
                doc.meta.bookId,
                para_id,
                concept,
                limiter=limiter,
                repair=repair,
                fail_reason=scenario,
            )
        # 前端检测到二次失败 → 降级（讲解用 good 后端，静态图 mock 生成）
        degraded = await diagram_service.degrade_diagram(
            storage, good, good, doc.meta.bookId, para_id, concept
        )
        assert degraded.kind == "degraded", f"{scenario} 场景必须有降级输出"
        assert degraded.staticImage, f"{scenario} 降级必须带静态图"
        assert degraded.explanation, f"{scenario} 降级必须带文字讲解"
        degraded_count += 1
    assert degraded_count == len(scenarios)  # 100% 有降级输出


# ---------- T2.7.3：同概念二次请求 100% 命中缓存 ----------


@pytest.mark.asyncio
async def test_cache_second_request_hits_and_zero_calls(env) -> None:
    storage, usage_log, backend, limiter, doc = env
    # 用独立概念避免与 T2.7.1 的缓存交叉
    concept = "国内生产总值"
    para_id = "c001-p0001"
    await diagram_service.generate_diagram(
        storage, backend, doc.meta.bookId, para_id, concept, limiter=limiter, session_id="acc2"
    )
    diagram_calls_before = len([e for e in usage_log.read_all() if e["purpose"] == "diagram"])
    backend_calls_before = len(backend.calls)

    second = await diagram_service.generate_diagram(
        storage, backend, doc.meta.bookId, para_id, concept, limiter=limiter, session_id="acc2"
    )
    third = await diagram_service.generate_diagram(
        storage, backend, doc.meta.bookId, para_id, "GDP", limiter=limiter, session_id="acc2"
    )  # GDP 为 concept 的同义表述
    assert second.cached is True and third.cached is True
    # 零新增生成调用（模型调用数与 usage 日志均不变）
    assert len(backend.calls) == backend_calls_before
    diagram_entries = [e for e in usage_log.read_all() if e["purpose"] == "diagram"]
    assert len(diagram_entries) == diagram_calls_before


# ---------- 组件约束抽查（防回归） ----------


def test_generated_component_meets_prompt_contract(env) -> None:
    """提示词工程的四大约束在产物上成立（透明/currentColor/自包含/ready 消息）。"""
    import asyncio

    storage, _usage, backend, limiter, doc = env
    result = asyncio.run(
        diagram_service.generate_diagram(
            storage, backend, doc.meta.bookId, "c001-p0001", "供需曲线",
            limiter=limiter, session_id="contract",
        )
    )
    html = result.componentHtml
    assert "background:transparent" in html
    assert "currentColor" in html
    assert "<script" in html  # 有交互脚本
    assert "http://" not in html.replace("http://www.w3.org", "")  # 无外部资源（W3C 命名空间除外）
    assert "parent.postMessage" in html  # ready 消息约定
