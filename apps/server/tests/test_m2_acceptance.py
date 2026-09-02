"""M2 验收（计划 Slice 2.7 / 上游 §6-M2）。

- T2.7.1：10 个真实晦涩概念生成图解（mock 确定性组件；人工评审「确实帮助理解」≥7/10
  属用户侧清单——见缺陷清单文档，真实模型配置后按同一清单复验）。
- T2.7.2：失败注入测试——生成产物不完整/引用未过校验/文生图不可达/讲解异常等
  场景逐类注入，100% 有降级输出（含纯文字降级与原文摘录兜底）。
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
# 场景逐类注入（评审 D6：不得用同一个垃圾响应冒充多种场景）：
#   A 响应非 JSON           → incomplete → 修复仍失败 → degrade
#   B 组件为空（componentHtml 缺失）→ incomplete → …
#   C 引用未过校验（quote 与原文不符）→ incomplete → …
#   D 文生图服务不可达      → degrade 纯文字讲解（无静态图）
#   E 讲解模型异常          → degrade 讲解退化为原文摘录
#   F 生成产物不完整绝不缓存为 interactive（评审 D0：空产物缓存毒化白屏）


class _RawBackend:
    """按脚本回放 content 的注入后端。script: 每次调用依次出队一个响应。"""

    provider = "failinject"

    def __init__(self, script: list[str]) -> None:
        self.script = list(script)
        self.calls = 0

    async def chat(self, role, messages, **kwargs):
        self.calls += 1
        content = self.script.pop(0) if self.script else "兜底垃圾响应"
        return type("R", (), {"content": content})()


class _ExplodingBackend:
    """讲解调用直接抛 ModelError（其余按脚本回放）。"""

    provider = "failinject"

    def __init__(self) -> None:
        from app.llm.errors import ModelError

        self._kind = ModelError("provider", "注入的讲解失败")

    async def chat(self, role, messages, **kwargs):
        raise self._kind


class _T2IBackend:
    """真实 provider 的文生图后端（可注入故障 transport）。"""

    provider = "cogview"

    def __init__(self, transport=None) -> None:
        self.config = {
            "endpoint": "https://t2i.invalid/v1",
            "api_key": "",
            "model": "cogview-test",
            "price": {"per_image": 0.06},
            "_transport": transport,
        }


_COMPONENTLESS = '{"componentHtml": "", "summary": "没图", "citations": []}'
_BAD_CITATION = (
    '{"componentHtml": "<svg>曲线</svg>", "summary": "有图", '
    '"citations": [{"paraId": "c001-p0001", "quote": "原文里不存在的一句话"}]}'
)


async def _degrade_all_injected(storage, doc, para_id: str, concept: str, fail_backend):
    """注入后端走完 首答→修复→降级 全链，返回降级产物。"""
    good = MockLLMClient(UsageLog(storage), responder=mock_behaviors.dispatch)
    limiter = RateLimiter(storage, limit=50)
    first = await diagram_service.generate_diagram(
        storage, fail_backend, doc.meta.bookId, para_id, concept, limiter=limiter
    )
    assert first.kind == "incomplete", "产物不完整必须是显式 incomplete，不得伪装 interactive"
    repair = await diagram_service.generate_diagram(
        storage, fail_backend, doc.meta.bookId, para_id, concept, limiter=limiter, repair=True
    )
    assert repair.kind == "incomplete"
    return await diagram_service.degrade_diagram(
        storage, good, good, doc.meta.bookId, para_id, concept
    )


@pytest.mark.asyncio
async def test_failure_injection_always_degrades(tmp_path) -> None:
    from app.storage import Storage

    storage = Storage(tmp_path)
    storage.ensure_layout()
    doc = _make_book(storage)

    scenarios: list[tuple[str, _RawBackend]] = [
        ("响应非 JSON", _RawBackend(["这不是 JSON，也没有组件。"] * 4)),
        ("组件为空", _RawBackend([_COMPONENTLESS] * 4)),
        ("引用未过校验", _RawBackend([_BAD_CITATION] * 4)),
    ]
    for i, (scenario, backend) in enumerate(scenarios):
        para_id = f"c001-p{i + 1:04d}"
        concept = f"失败概念{i}"
        degraded = await _degrade_all_injected(storage, doc, para_id, concept, backend)
        assert degraded.kind == "degraded", f"{scenario} 场景必须有降级输出"
        assert degraded.staticImage, f"{scenario} 降级必须带静态图"
        assert degraded.explanation, f"{scenario} 降级必须带文字讲解"


@pytest.mark.asyncio
async def test_incomplete_result_never_cached_as_interactive(tmp_path) -> None:
    """评审 D0：空产物落缓存后，后续请求也拿到 incomplete（而非空 interactive 白屏）。"""
    from app.storage import Storage

    storage = Storage(tmp_path)
    storage.ensure_layout()
    doc = _make_book(storage)
    backend = _RawBackend([_COMPONENTLESS] * 4)
    limiter = RateLimiter(storage, limit=50)

    first = await diagram_service.generate_diagram(
        storage, backend, doc.meta.bookId, "c001-p0001", "毒化概念", limiter=limiter
    )
    assert first.kind == "incomplete" and first.componentHtml == ""
    # 全新会话再请求：命中的是 incomplete 缓存，前端可据此走修复/降级，永不白屏
    second = await diagram_service.generate_diagram(
        storage, backend, doc.meta.bookId, "c001-p0001", "毒化概念", limiter=limiter
    )
    assert second.cached is True
    assert second.kind == "incomplete" and second.componentHtml == ""


@pytest.mark.asyncio
async def test_degrade_t2i_failure_falls_back_to_text(tmp_path) -> None:
    """评审 D4：文生图服务不可达 → 纯文字讲解降级，绝不 500。"""
    import httpx
    from app.storage import Storage

    storage = Storage(tmp_path)
    storage.ensure_layout()
    doc = _make_book(storage)
    usage_log = UsageLog(storage)
    good = MockLLMClient(usage_log, responder=mock_behaviors.dispatch)

    def boom(request):
        raise httpx.ConnectError("注入：文生图服务不可达")

    t2i = _T2IBackend(transport=httpx.MockTransport(boom))
    degraded = await diagram_service.degrade_diagram(
        storage, good, t2i, doc.meta.bookId, "c001-p0001", "降级概念",
        session_id="s-t2i", usage_log=usage_log,
    )
    assert degraded.kind == "degraded"
    assert degraded.staticImage == "", "文生图失败应退化为纯文字讲解（无静态图）"
    assert degraded.explanation, "纯文字降级必须保留讲解"
    assert degraded.summary == "（纯文字讲解）"
    # 费用可见（红线 3）：失败的文生图调用也入账
    static_calls = [e for e in usage_log.read_all() if e["purpose"] == "diagram_static"]
    assert len(static_calls) == 1 and static_calls[0]["status"].startswith("error:")
    assert static_calls[0]["sessionId"] == "s-t2i"


@pytest.mark.asyncio
async def test_degrade_t2i_success_records_flat_cost(tmp_path) -> None:
    """文生图成功：按张计价入账（costCny=per_image，token 恒 0）。"""
    import httpx
    from app.storage import Storage

    storage = Storage(tmp_path)
    storage.ensure_layout()
    doc = _make_book(storage)
    usage_log = UsageLog(storage)
    good = MockLLMClient(usage_log, responder=mock_behaviors.dispatch)

    png = b"\x89PNG\r\n\x1a\nfake"

    def handler(request):
        if request.url.path.endswith("generations"):
            return httpx.Response(200, json={"data": [{"url": "https://t2i.invalid/v1/img"}]})
        return httpx.Response(200, content=png)

    t2i = _T2IBackend(transport=httpx.MockTransport(handler))
    degraded = await diagram_service.degrade_diagram(
        storage, good, t2i, doc.meta.bookId, "c001-p0002", "计费概念",
        session_id="s-ok", usage_log=usage_log,
    )
    assert degraded.kind == "degraded" and degraded.staticImage.endswith(".png")
    calls = [e for e in usage_log.read_all() if e["purpose"] == "diagram_static"]
    assert len(calls) == 1
    assert calls[0]["status"] == "ok" and calls[0]["costCny"] == 0.06


@pytest.mark.asyncio
async def test_degrade_explain_failure_uses_excerpt(tmp_path) -> None:
    """评审 D4/E：讲解模型异常 → 退化为原文摘录（仍有降级输出）。"""
    from app.storage import Storage

    storage = Storage(tmp_path)
    storage.ensure_layout()
    doc = _make_book(storage)
    usage_log = UsageLog(storage)
    good = MockLLMClient(usage_log, responder=mock_behaviors.dispatch)

    degraded = await diagram_service.degrade_diagram(
        storage, _ExplodingBackend(), good, doc.meta.bookId, "c001-p0003", "讲解失败概念"
    )
    assert degraded.kind == "degraded"
    para = doc.chapters[0].paras[2]
    assert degraded.explanation == para.text[:120]  # 原文摘录兜底
    assert degraded.staticImage, "讲解失败不影响静态图"


@pytest.mark.asyncio
async def test_mock_static_svg_escapes_concept(tmp_path) -> None:
    """评审 D9：mock 静态图中的概念必须 XML 转义（防非法 SVG/注入）。"""
    from app.storage import Storage

    storage = Storage(tmp_path)
    storage.ensure_layout()
    doc = _make_book(storage)
    usage_log = UsageLog(storage)
    good = MockLLMClient(usage_log, responder=mock_behaviors.dispatch)

    degraded = await diagram_service.degrade_diagram(
        storage, good, good, doc.meta.bookId, "c001-p0004", "a<b&c"
    )
    assert degraded.staticImage
    svg = (
        storage.diagrams_dir(doc.meta.bookId) / "files" / degraded.staticImage.split("/")[-1]
    ).read_text(encoding="utf-8")
    assert "a&lt;b&amp;c" in svg and "a<b&c" not in svg


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
