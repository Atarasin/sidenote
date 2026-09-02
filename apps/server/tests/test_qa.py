"""引用式问答（计划 Slice 1.5）：引用真实性校验、无据拒答、API 开放。"""

from __future__ import annotations

import json

import pytest
from app.knowledge import mock_behaviors
from app.knowledge.builder import build_book_knowledge
from app.knowledge.mock_behaviors import qa as qa_behavior
from app.llm.mock import MockLLMClient
from app.llm.types import ChatMessage
from app.llm.usage import UsageLog
from app.qa.service import answer_question, validate_citations

from test_knowledge import make_doc


@pytest.fixture
def prepared(storage):
    doc = make_doc()
    storage.write_bookdoc(doc)
    usage_log = UsageLog(storage)
    mock_llm = MockLLMClient(usage_log, responder=mock_behaviors.dispatch)
    return storage, usage_log, mock_llm, doc


@pytest.mark.asyncio
async def test_answer_with_real_citations(prepared) -> None:
    storage, usage_log, backend, doc = prepared
    await build_book_knowledge(storage, doc.meta.bookId, backend)
    result = await answer_question(
        storage, usage_log, backend, doc.meta.bookId, "均衡价格是如何形成的", chapter_id="c001"
    )
    assert result.hasBasis is True
    assert result.citations, "有据回答必须携带引用（红线 2）"
    # 引用真实性：quote 逐字来自对应段落（服务层已校验，双保险再验一次）
    paras = {p.id: p.text for ch in doc.chapters for p in ch.paras}
    for cite in result.citations:
        assert cite.quote in paras[cite.paraId]


@pytest.mark.asyncio
async def test_cross_chapter_question_uses_witness(prepared) -> None:
    storage, usage_log, backend, doc = prepared
    await build_book_knowledge(storage, doc.meta.bookId, backend)
    result = await answer_question(
        storage, usage_log, backend, doc.meta.bookId, "全书对供给弹性怎么讲", chapter_id="c001"
    )
    assert result.witnessUsed is True  # 跨章信号触发旁证装载
    assert result.hasBasis is True
    # 旁证章内容被实际引用（第一章也有弹性句，故只要求包含 c002 引用）
    assert any(c.paraId.startswith("c002") for c in result.citations)


@pytest.mark.asyncio
async def test_no_basis_refuses(prepared) -> None:
    storage, usage_log, backend, doc = prepared
    await build_book_knowledge(storage, doc.meta.bookId, backend)
    result = await answer_question(
        storage,
        usage_log,
        backend,
        doc.meta.bookId,
        "量子纠缠和薛定谔的猫是什么",
        chapter_id="c001",
    )
    assert result.answer == "书中未涉及"  # T1.5.3 无据拒答
    assert result.citations == []
    assert result.hasBasis is False


def test_validate_citations_rules() -> None:
    doc = make_doc()
    paras = [p for ch in doc.chapters for p in ch.paras]
    first = paras[0]
    # 合法：逐字引用
    ok = validate_citations(doc, [{"paraId": first.id, "quote": first.text}])
    assert len(ok) == 1
    # quote 与段落不符 → 丢弃
    bad = validate_citations(doc, [{"paraId": first.id, "quote": "不存在的原文"}])
    assert bad == []
    # paraId 不存在 → 丢弃
    assert validate_citations(doc, [{"paraId": "c999-p9999", "quote": first.text}]) == []
    # 空白差异容忍
    ok2 = validate_citations(
        doc, [{"paraId": first.id, "quote": "  " + first.text[:5] + "  "}]
    )
    assert len(ok2) == 1


@pytest.mark.asyncio
async def test_invalid_citations_trigger_retry_then_refuse(storage) -> None:
    """声称有据但引用对不上 → 丢弃并重答；重答仍无有效引用 → 拒答（T1.5.2）。"""
    doc = make_doc()
    storage.write_bookdoc(doc)
    usage_log = UsageLog(storage)
    calls = {"n": 0}

    class BadCiteBackend:
        provider = "badcite"

        async def chat(self, role, messages, **kwargs):
            calls["n"] += 1
            return type(
                "R",
                (),
                {
                    "content": json.dumps(
                        {
                            "answer": "编造的回答",
                            "citations": [{"paraId": "c001-p0001", "quote": "完全编造的引用"}],
                            "hasBasis": True,
                        },
                        ensure_ascii=False,
                    )
                },
            )()

    # 预置 knowledge（避免走 mock 构建）
    good_mock = MockLLMClient(usage_log, responder=mock_behaviors.dispatch)
    await build_book_knowledge(storage, doc.meta.bookId, good_mock)

    result = await answer_question(
        storage, usage_log, BadCiteBackend(), doc.meta.bookId, "均衡价格", chapter_id="c001"
    )
    assert calls["n"] == 2  # 首答 + 重答一次
    assert result.retried is True
    assert result.answer == "书中未涉及"  # 重答仍无效引用 → 拒答
    assert result.citations == []


@pytest.mark.asyncio
async def test_retry_recovers_with_valid_citations(storage) -> None:
    """首答引用不实，重答给出真实引用 → 采纳重答结果。"""
    doc = make_doc()
    storage.write_bookdoc(doc)
    usage_log = UsageLog(storage)
    good_mock = MockLLMClient(usage_log, responder=mock_behaviors.dispatch)
    await build_book_knowledge(storage, doc.meta.bookId, good_mock)
    real_para = doc.chapters[0].paras[0]
    calls = {"n": 0}

    class FlakyCiteBackend:
        provider = "flakycite"

        async def chat(self, role, messages, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                content = json.dumps(
                    {
                        "answer": "首答",
                        "citations": [{"paraId": real_para.id, "quote": "编造"}],
                        "hasBasis": True,
                    },
                    ensure_ascii=False,
                )
            else:
                content = json.dumps(
                    {
                        "answer": "重答正确",
                        "citations": [{"paraId": real_para.id, "quote": real_para.text}],
                        "hasBasis": True,
                    },
                    ensure_ascii=False,
                )
            return type("R", (), {"content": content})()

    result = await answer_question(
        storage, usage_log, FlakyCiteBackend(), doc.meta.bookId, "供给与需求", chapter_id="c001"
    )
    assert result.retried is True
    assert result.answer == "重答正确"
    assert result.citations[0].quote == real_para.text


def test_mock_qa_behavior_shapes() -> None:
    msgs = [
        ChatMessage("system", "s"),
        ChatMessage(
            "user",
            "【当前章节：第一章】\n"
            "[c001-p0001] 供给与需求是经济学最基本的一对概念。\n"
            "\n【问题】供给与需求是什么",
        ),
    ]
    data = json.loads(qa_behavior(msgs, "long_text_qa", "qa"))
    assert data["hasBasis"] is True
    assert data["citations"][0]["paraId"] == "c001-p0001"


def test_ask_api_endpoint(client, storage, tiny_epub) -> None:
    import time

    resp = client.post(
        "/api/books", files={"file": ("t.epub", tiny_epub.open("rb"), "application/epub+zip")}
    )
    book_id = resp.json()["bookId"]
    client.post(f"/api/books/{book_id}/knowledge")
    deadline = time.time() + 10
    while time.time() < deadline:
        if client.get(f"/api/books/{book_id}/knowledge").status_code == 200:
            break
        time.sleep(0.1)
    ask = client.post(
        f"/api/books/{book_id}/ask",
        json={"question": "供给与需求是什么概念", "chapterId": "c001"},
    )
    assert ask.status_code == 200
    body = ask.json()
    assert body["hasBasis"] is True
    assert body["citations"], "回答必须带引用（红线 2）"
    assert body["citations"][0]["paraId"].startswith("c001")
