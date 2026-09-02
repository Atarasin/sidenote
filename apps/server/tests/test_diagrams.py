"""图解后端（计划 Slice 2.1~2.5）：生成主链路、修复重试、降级、缓存、成本闸门。"""

from __future__ import annotations

import pytest
from app.diagrams import service as diagram_service
from app.diagrams.models import load_cached, make_cache_key
from app.diagrams.normalize import normalize_concept
from app.diagrams.rates import RateLimiter
from app.knowledge import mock_behaviors
from app.llm.mock import MockLLMClient
from app.llm.usage import UsageLog
from app.qa.service import validate_citations

from test_knowledge import make_doc


@pytest.fixture
def env(tmp_path):
    from app.storage import Storage

    storage = Storage(tmp_path)
    storage.ensure_layout()
    doc = make_doc()
    storage.write_bookdoc(doc)
    usage_log = UsageLog(storage)
    mock_llm = MockLLMClient(usage_log, responder=mock_behaviors.dispatch)
    limiter = RateLimiter(storage, limit=3, window_seconds=3600)
    return storage, usage_log, mock_llm, limiter, doc


# ---------- T2.1.3 概念规范化 ----------


def test_normalize_concept_synonyms() -> None:
    assert normalize_concept("供需曲线") == normalize_concept("供给需求曲线")
    assert normalize_concept("  供需均衡 ") == normalize_concept("供给与需求均衡")
    assert normalize_concept("弹性（经济学）") == normalize_concept("弹性")
    assert make_cache_key("b", "c001-p0001", normalize_concept("供需曲线")) == make_cache_key(
        "b", "c001-p0001", normalize_concept("供给需求曲线")
    )


# ---------- T2.1.2 生成主链路 ----------


@pytest.mark.asyncio
async def test_generate_interactive_diagram(env) -> None:
    storage, usage_log, backend, limiter, doc = env
    result = await diagram_service.generate_diagram(
        storage,
        backend,
        doc.meta.bookId,
        "c001-p0001",
        "供需曲线",
        limiter=limiter,
        session_id="s1",
    )
    assert result.kind == "interactive"
    assert result.cached is False
    assert "currentColor" in result.componentHtml  # UI §3.4 双容器配色约束
    assert "background:transparent" in result.componentHtml
    assert "sidenote:ready" in result.componentHtml  # 沙箱渲染检测约定
    assert result.citations, "图解必须带引用（红线 2）"
    assert validate_citations(
        doc, [{"paraId": c.paraId, "quote": c.quote} for c in result.citations]
    )
    assert load_cached(storage, doc.meta.bookId, result.cacheKey) is not None
    assert any(e["purpose"] == "diagram" for e in usage_log.read_all())


@pytest.mark.asyncio
async def test_cache_hit_no_extra_generation(env) -> None:
    """T2.4.1 / T2.7.3：同概念二次请求 100% 命中缓存、零新增生成调用。"""
    storage, _usage, backend, limiter, doc = env
    first = await diagram_service.generate_diagram(
        storage, backend, doc.meta.bookId, "c001-p0001", "供需曲线", limiter=limiter
    )
    calls_after_first = len(backend.calls)
    second = await diagram_service.generate_diagram(
        storage,  # 同义表述也应命中同一缓存键（T2.1.3）
        backend,
        doc.meta.bookId,
        "c001-p0001",
        "供给需求曲线",
        limiter=limiter,
    )
    assert second.cached is True
    assert second.cacheKey == first.cacheKey
    assert len(backend.calls) == calls_after_first


# ---------- T2.2.3 修复重试（至多 1 次） ----------


@pytest.mark.asyncio
async def test_repair_once_then_blocked(env) -> None:
    storage, _usage, backend, limiter, doc = env
    first = await diagram_service.generate_diagram(
        storage, backend, doc.meta.bookId, "c001-p0001", "均衡价格", limiter=limiter
    )
    assert first.attempts == 1
    repaired = await diagram_service.generate_diagram(
        storage,
        backend,
        doc.meta.bookId,
        "c001-p0001",
        "均衡价格",
        limiter=limiter,
        repair=True,
        fail_reason="渲染超时",
    )
    assert repaired.attempts == 2
    assert repaired.cached is False
    third = await diagram_service.generate_diagram(
        storage,
        backend,
        doc.meta.bookId,
        "c001-p0001",
        "均衡价格",
        limiter=limiter,
        repair=True,
        fail_reason="仍然失败",
    )
    assert third.cached is True  # 第二次修复被拒绝（上游 D3：只重试 1 次）


# ---------- T2.3 降级链路 ----------


@pytest.mark.asyncio
async def test_degrade_writes_cache_and_static_image(env) -> None:
    storage, _usage, backend, limiter, doc = env
    degraded = await diagram_service.degrade_diagram(
        storage, backend, backend, doc.meta.bookId, "c001-p0001", "均衡价格"
    )
    assert degraded.kind == "degraded"
    assert degraded.staticImage.startswith("files/")
    assert degraded.staticImage.endswith(".svg")
    file_path = storage.diagrams_dir(doc.meta.bookId) / degraded.staticImage
    assert file_path.is_file()
    assert degraded.explanation
    again = await diagram_service.degrade_diagram(
        storage, backend, backend, doc.meta.bookId, "c001-p0001", "市场均衡价格"
    )
    assert again.cached is True and again.kind == "degraded"
    repaired = await diagram_service.generate_diagram(
        storage,
        backend,
        doc.meta.bookId,
        "c001-p0001",
        "均衡价格",
        limiter=limiter,
        repair=True,
    )
    assert repaired.cached is True and repaired.kind == "degraded"


# ---------- T2.5.2 会话频率限制 ----------


@pytest.mark.asyncio
async def test_rate_limit_blocks_and_reports(env) -> None:
    storage, _usage, backend, limiter, doc = env
    for i, concept in enumerate(["均衡价格", "需求价格弹性", "边际效用"]):
        para = f"c001-p000{(i % 4) + 1}"
        result = await diagram_service.generate_diagram(
            storage, backend, doc.meta.bookId, para, concept, limiter=limiter, session_id="s1"
        )
        assert result.cached is False
    with pytest.raises(diagram_service.DiagramLimited) as ei:
        await diagram_service.generate_diagram(
            storage,
            backend,
            doc.meta.bookId,
            "c001-p0002",
            "外部性",
            limiter=limiter,
            session_id="s1",
        )
    assert ei.value.state.used == 3 and ei.value.state.limit == 3
    hit = await diagram_service.generate_diagram(
        storage,
        backend,
        doc.meta.bookId,
        "c001-p0001",
        "市场均衡价格",  # 循环中「均衡价格」的同义表述 → 命中缓存、不占名额
        limiter=limiter,
        session_id="s1",
    )
    assert hit.cached is True
    other = await diagram_service.generate_diagram(
        storage, backend, doc.meta.bookId, "c001-p0002", "外部性", limiter=limiter, session_id="s2"
    )
    assert other.cached is False


# ---------- API 端到端 ----------


def test_diagram_api_flow(client, storage, tiny_epub) -> None:
    import time

    resp = client.post(
        "/api/books", files={"file": ("t.epub", tiny_epub.open("rb"), "application/epub+zip")}
    )
    book_id = resp.json()["bookId"]
    deadline = time.time() + 10
    while time.time() < deadline and client.get(f"/api/books/{book_id}/bookdoc").status_code != 200:
        time.sleep(0.1)

    create = client.post(
        f"/api/books/{book_id}/diagrams",
        json={"paraId": "c001-p0001", "concept": "供需曲线", "sessionId": "web"},
    )
    assert create.status_code == 200
    body = create.json()
    assert body["kind"] == "interactive"
    assert body["rateLimit"]["used"] == 1
    assert body["rateLimit"]["limit"] == 20

    got = client.get(f"/api/books/{book_id}/diagrams/c001-p0001/供需曲线")
    assert got.status_code == 200 and got.json()["cached"] is True

    degraded = client.post(
        f"/api/books/{book_id}/diagrams/degrade",
        json={"paraId": "c001-p0001", "concept": "供需曲线", "sessionId": "web"},
    )
    static_path = degraded.json()["staticImage"]
    img = client.get(f"/api/books/{book_id}/diagrams-files/{static_path.split('/')[-1]}")
    assert img.status_code == 200

    summary = client.get("/api/usage/summary", params={"sessionId": "web"})
    assert summary.status_code == 200
    data = summary.json()
    assert data["rateLimit"]["limit"] == 20
    assert data["totalCalls"] >= 1


def test_rate_limiter_unit(tmp_path) -> None:
    from app.storage import Storage

    limiter = RateLimiter(Storage(tmp_path), limit=1, window_seconds=3600)
    assert not limiter.consume("s").limited
    state = limiter.check("s")
    assert state.limited and state.used == 1
    state2 = limiter.consume("s")
    assert state2.limited and state2.used == 1
