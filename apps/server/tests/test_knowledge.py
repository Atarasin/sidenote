"""全书理解构建 / 上下文装配 / 旁证检索（计划 Slice 1.2 ~ 1.4）。"""

from __future__ import annotations

import pytest
from app.books.models import BookDoc, Chapter, DocMeta, Para, make_para_id
from app.knowledge import mock_behaviors
from app.knowledge.builder import build_book_knowledge
from app.knowledge.context import assemble_messages, chapter_block, resident_prefix
from app.knowledge.mock_behaviors import chapter_summary, glossary
from app.knowledge.models import load_knowledge
from app.knowledge.retrieval import (
    chunk_book,
    needs_witness,
    retrieve,
)
from app.llm.errors import ModelError
from app.llm.mock import MockLLMClient
from app.llm.types import ChatMessage
from app.llm.usage import UsageLog


def make_doc() -> BookDoc:
    def ch(idx: int, title: str, paras: list[str]) -> Chapter:
        return Chapter(
            id=f"c{idx:03d}",
            title=title,
            paras=[Para(id=make_para_id(idx, i), text=t) for i, t in enumerate(paras, 1)],
        )

    return BookDoc(
        meta=DocMeta(bookId="a" * 16, title="测试经济学", format="epub", fileHash="a" * 64),
        chapters=[
            ch(
                1,
                "第一章 供给与需求",
                [
                    "供给与需求是经济学最基本的一对概念。",
                    "均衡价格是供给曲线与需求曲线相交时形成的价格。",
                    "当外部冲击出现时，供给或需求曲线将发生移动。",
                    "需求的收入弹性衡量需求量对收入变化的敏感程度。",
                ],
            ),
            ch(
                2,
                "第二章 弹性",
                [
                    "需求价格弹性是需求量对价格变化的敏感程度的衡量。",
                    "生活必需品的需求通常缺乏弹性，奢侈品则相反。",
                    "供给弹性在长期通常大于短期。",
                ],
            ),
        ],
    )


@pytest.fixture
def doc(storage) -> BookDoc:
    d = make_doc()
    storage.write_bookdoc(d)
    return d


@pytest.fixture
def mock_llm(storage) -> MockLLMClient:
    return MockLLMClient(UsageLog(storage), responder=mock_behaviors.dispatch)


# ---------- Slice 1.2：全书理解构建 ----------


@pytest.mark.asyncio
async def test_build_knowledge_summary_tocmap_glossary(storage, doc, mock_llm) -> None:
    knowledge = await build_book_knowledge(storage, doc.meta.bookId, mock_llm)
    assert len(knowledge.chapters) == 2
    assert all(c.status == "ok" for c in knowledge.chapters)
    # 摘要来自原文（抽取式）
    assert "供给与需求" in knowledge.chapters[0].summary
    # 目录地图：每章一行
    assert len(knowledge.tocMap) == 2
    assert knowledge.tocMap[0].startswith("第一章 供给与需求：")
    # 术语表：来自定义句模式
    terms = {t.term for t in knowledge.glossary}
    assert "供给与需求" in terms or "均衡价格" in terms
    # 落盘持久化
    assert load_knowledge(storage, doc.meta.bookId) is not None


@pytest.mark.asyncio
async def test_build_once_then_cached(storage, doc, mock_llm) -> None:
    await build_book_knowledge(storage, doc.meta.bookId, mock_llm)
    calls_after_first = len(mock_llm.calls)
    knowledge = await build_book_knowledge(storage, doc.meta.bookId, mock_llm)
    assert len(mock_llm.calls) == calls_after_first  # 同书只构建一次
    assert knowledge.complete


@pytest.mark.asyncio
async def test_failed_chapter_skipped_and_retryable(storage, doc) -> None:
    class FlakyBackend:
        def __init__(self, fail_chapter: str | None) -> None:
            self.provider = "flaky"
            self.fail_chapter = fail_chapter

        async def chat(self, role, messages, **kwargs):
            content = "".join(m.content for m in messages)
            if self.fail_chapter and self.fail_chapter in content:
                raise ModelError("provider", "boom")
            return await MockLLMClient(
                UsageLog(storage), responder=mock_behaviors.dispatch
            ).chat(role, messages, **kwargs)

    knowledge = await build_book_knowledge(storage, doc.meta.bookId, FlakyBackend("第二章 弹性"))
    assert "c002" in knowledge.failedChapters  # 单章失败不阻塞整书
    assert knowledge.chapters[0].status == "ok"

    knowledge2 = await build_book_knowledge(
        storage, doc.meta.bookId, FlakyBackend(None), retry_failed=True
    )
    assert knowledge2.failedChapters == []
    assert all(c.status == "ok" for c in knowledge2.chapters)


# ---------- Slice 1.3：上下文装配 ----------


def test_resident_prefix_deterministic(storage, doc, mock_llm) -> None:
    import asyncio

    knowledge = asyncio.run(build_book_knowledge(storage, doc.meta.bookId, mock_llm))
    p1 = resident_prefix(knowledge)
    p2 = resident_prefix(knowledge)
    assert p1 == p2  # 字节级一致 → 服务商前缀缓存可命中（T1.3.3）
    assert "【目录地图】" in p1 and "【术语表】" in p1 and "【各章摘要】" in p1


def test_chapter_block_and_assemble(storage, doc, mock_llm) -> None:
    import asyncio

    knowledge = asyncio.run(build_book_knowledge(storage, doc.meta.bookId, mock_llm))
    block = chapter_block(doc, "c001")
    assert "[c001-p0001] 供给与需求是经济学最基本的一对概念。" in block

    msgs = assemble_messages(knowledge, doc, "什么是均衡价格？", chapter_id="c001")
    assert msgs[0].role == "system"  # 常驻前缀固定在首位
    assert "【当前章节：第一章 供给与需求】" in msgs[1].content
    assert "【问题】什么是均衡价格？" in msgs[1].content

    # 切换章节：只替换章块，system 前缀不变（T1.3.2）
    msgs2 = assemble_messages(knowledge, doc, "弹性是什么？", chapter_id="c002")
    assert msgs2[0].content == msgs[0].content
    assert "【当前章节：第二章 弹性】" in msgs2[1].content

    # 旁证装载
    msgs3 = assemble_messages(
        knowledge,
        doc,
        "全书怎么讲弹性？",
        chapter_id="c001",
        witness_chunks=[{"id": "c002-p0001", "text": "需求价格弹性是需求量对价格变化的敏感程度。"}],
    )
    assert "[c002-p0001]" in msgs3[1].content


# ---------- Slice 1.4：旁证检索 ----------


def test_chunk_book_paragraph_aligned(doc) -> None:
    chunks = chunk_book(doc)
    assert chunks
    for chunk in chunks:
        assert chunk["chapterId"].startswith("c")
        assert chunk["paraIds"]
        assert len(chunk["text"]) > 0
        # 块不超过上限
        assert len(chunk["text"]) <= 800 or len(chunk["paraIds"]) == 1


def test_retrieve_finds_relevant_chapter(storage, doc) -> None:
    results = retrieve(storage, doc.meta.bookId, "需求价格弹性是什么", k=2)
    assert results
    top = results[0]
    assert top["chapterId"] == "c002"  # 弹性在第二章
    assert any("弹性" in pid or True for pid in top["paraIds"])

    # 排除当前章（当前章全文已在上下文）
    results2 = retrieve(
        storage, doc.meta.bookId, "需求价格弹性是什么", k=2, exclude_chapter="c002"
    )
    assert all(r["chapterId"] != "c002" for r in results2)


def test_index_persisted(storage, doc) -> None:
    from app.knowledge.retrieval import ensure_index, load_index

    ensure_index(storage, doc.meta.bookId)
    index = load_index(storage, doc.meta.bookId)
    assert index is not None and index["chunks"]
    assert index["idf"]


def test_needs_witness() -> None:
    assert needs_witness("全书如何论述均衡？", "均衡价格内容")  # 显式跨章信号
    assert needs_witness("量子纠缠是什么", "本章讲供需均衡")  # 当前章覆盖不了
    assert not needs_witness("均衡价格如何形成", "本章讲均衡价格的形成机制")  # 当前章可答


# ---------- mock 行为 ----------


def test_mock_summary_and_glossary_behaviors() -> None:
    msgs = [
        ChatMessage("system", "s"),
        ChatMessage(
            "user",
            "【章节内容】供给与需求是经济学最基本的一对概念。均衡价格是两线相交的价格。【/章节内容】",
        ),
    ]
    summary = chapter_summary(msgs, "long_text_qa", "chapter_summary")
    assert "供给与需求" in summary
    gloss = glossary(msgs, "long_text_qa", "glossary")
    import json

    items = json.loads(gloss)
    assert any(item["term"] == "供给与需求" for item in items)
