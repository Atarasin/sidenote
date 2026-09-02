"""涂写意图解析（计划 Slice 3.2）：mock 匹配、链路转接、API 行为。"""

from __future__ import annotations

import json

import pytest
from app.knowledge import mock_behaviors
from app.llm.mock import MockLLMClient
from app.llm.usage import UsageLog
from app.scribbles import service as scribble_service

from test_knowledge import make_doc


@pytest.fixture
def env(tmp_path):
    from app.storage import Storage

    storage = Storage(tmp_path)
    storage.ensure_layout()
    doc = make_doc()
    storage.write_bookdoc(doc)
    usage_log = UsageLog(storage)
    backend = MockLLMClient(usage_log, responder=mock_behaviors.dispatch)
    return storage, usage_log, backend, doc


CANDIDATES_OF = lambda doc, *idxs: [  # noqa: E731 - 测试内简写
    {"paraId": doc.chapters[0].paras[i].id, "text": doc.chapters[0].paras[i].text}
    for i in idxs
]


@pytest.mark.asyncio
async def test_mock_intent_matches_note_to_candidate(env) -> None:
    _storage, _usage, backend, doc = env
    paras = doc.chapters[0].paras
    result = await scribble_service.parse_scribble_intent(
        backend,
        image="data:image/png;base64,AAAA",
        note=paras[1].text[:6],  # 附言直接取自目标段落 → 关键词必然命中
        candidates=CANDIDATES_OF(doc, 0, 1, 2),
        book_id=doc.meta.bookId,
        session_id="s1",
    )
    assert result["paraId"] == paras[1].id
    assert result["question"] == paras[1].text[:6]
    assert result["route"] == "qa"


@pytest.mark.asyncio
async def test_mock_intent_diagram_route_and_concept(env) -> None:
    _storage, _usage, backend, doc = env
    paras = doc.chapters[0].paras
    result = await scribble_service.parse_scribble_intent(
        backend,
        image="data:image/png;base64,AAAA",
        note="画一个供需曲线图",
        candidates=CANDIDATES_OF(doc, 0),
        book_id=doc.meta.bookId,
    )
    assert result["route"] == "diagram"
    assert result["concept"] == "供需曲线"
    assert result["paraId"] == paras[0].id


@pytest.mark.asyncio
async def test_mock_intent_empty_note_uses_first_candidate(env) -> None:
    _storage, _usage, backend, doc = env
    result = await scribble_service.parse_scribble_intent(
        backend,
        image="data:image/png;base64,AAAA",
        note="",
        candidates=CANDIDATES_OF(doc, 2),
        book_id=doc.meta.bookId,
    )
    assert result["paraId"] == doc.chapters[0].paras[2].id
    assert result["question"].startswith("请讲解：")
    assert result["route"] == "qa"


@pytest.mark.asyncio
async def test_intent_usage_recorded(env) -> None:
    _storage, usage_log, backend, doc = env
    await scribble_service.parse_scribble_intent(
        backend,
        image="data:image/png;base64,AAAA",
        note="随便问问",
        candidates=CANDIDATES_OF(doc, 0),
        book_id=doc.meta.bookId,
        session_id="s-usage",
    )
    entries = [e for e in usage_log.read_all() if e["purpose"] == "scribble_intent"]
    assert len(entries) == 1
    assert entries[0]["role"] == "vision"
    assert entries[0]["sessionId"] == "s-usage"
    # 视觉消息带 image 分段：mock 只按文本段估 token（不为图片乱计费）
    assert entries[0]["promptTokens"] > 0


@pytest.mark.asyncio
async def test_invalid_model_output_falls_back_to_qa(tmp_path) -> None:
    """真实模型输出越界（paraId 不在候选/route 非法/JSON 坏）→ 回退 QA 兜底。"""

    class BadVision:
        provider = "badvision"

        async def chat(self, role, messages, **kwargs):
            return type("R", (), {"content": "我认为是段落 c999-p9999，route=teleport"})()

    from app.storage import Storage

    storage = Storage(tmp_path)
    storage.ensure_layout()
    doc = make_doc()
    storage.write_bookdoc(doc)
    result = await scribble_service.parse_scribble_intent(
        BadVision(),
        image="data:image/png;base64,AAAA",
        note="这是什么",
        candidates=CANDIDATES_OF(doc, 0, 1),
        book_id=doc.meta.bookId,
    )
    assert result["paraId"] == doc.chapters[0].paras[0].id  # 首个候选兜底
    assert result["route"] == "qa"


@pytest.mark.asyncio
async def test_model_error_falls_back(env) -> None:
    """视觉模型调用失败（网络等）不阻断用户动线：回退 QA。"""

    class Exploding:
        provider = "boom"

        async def chat(self, role, messages, **kwargs):
            raise RuntimeError("网络中断")

    _storage, _usage, _backend, doc = env
    result = await scribble_service.parse_scribble_intent(
        Exploding(),
        image="data:image/png;base64,AAAA",
        note="附言",
        candidates=CANDIDATES_OF(doc, 0),
        book_id=doc.meta.bookId,
    )
    assert result["route"] == "qa" and result["question"] == "附言"


def test_scribble_intent_api_flow(client, storage, tiny_epub) -> None:
    import time

    resp = client.post(
        "/api/books", files={"file": ("t.epub", tiny_epub.open("rb"), "application/epub+zip")}
    )
    book_id = resp.json()["bookId"]
    deadline = time.time() + 10
    while time.time() < deadline and client.get(f"/api/books/{book_id}/bookdoc").status_code != 200:
        time.sleep(0.1)

    ok = client.post(
        f"/api/books/{book_id}/scribbles/intent",
        json={
            "image": "data:image/png;base64,AAAA",
            "note": "",
            "candidates": [{"paraId": "c001-p0001", "text": "任意文本"}],
            "sessionId": "web",
        },
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["paraId"] == "c001-p0001"
    assert body["route"] == "qa"

    ghost = client.post(
        f"/api/books/{'0' * 16}/scribbles/intent",
        json={
            "image": "data:image/png;base64,AAAA",
            "note": "",
            "candidates": [{"paraId": "c001-p0001", "text": "任意文本"}],
        },
    )
    assert ghost.status_code == 404

    unknown = client.post(
        f"/api/books/{book_id}/scribbles/intent",
        json={
            "image": "data:image/png;base64,AAAA",
            "note": "",
            "candidates": [{"paraId": "c999-p9999", "text": "不在书里的段落"}],
        },
    )
    assert unknown.status_code == 400


def test_intent_user_text_format() -> None:
    from app.scribbles.prompts import intent_user_text

    text = intent_user_text("帮忙讲解", [{"paraId": "c001-p0001", "text": "段落一"}])
    assert "【附言】帮忙讲解" in text
    assert "[c001-p0001] 段落一" in text  # mock 应答器与真实提示词共享该格式
    assert json.dumps({})  # json 可用性自检（避免环境缺库误报）
