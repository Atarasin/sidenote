"""M1 验收（计划 Slice 1.6 / 上游 §6-M1）。

- T1.6.1：20 个跨章节问题，引用出处 100% 真实可查。
- T1.6.2：无依据问题集，100% 明确回答「书中未涉及」。

用合成多章书 + mock 检索式问答执行全链路（装配 → 模型 → 引用校验 → 拒答）。
真实模型（DeepSeek/Kimi）接入后由用户按同一清单复验（配置 config.local.yaml 即可切换）。
"""

from __future__ import annotations

import pytest
from app.knowledge import mock_behaviors
from app.knowledge.builder import build_book_knowledge
from app.llm.mock import MockLLMClient
from app.llm.usage import UsageLog
from app.qa.service import answer_question

# ---------- 合成多章书：覆盖 6 章经济主题，保证跨章问题有真实出处 ----------

CHAPTERS: list[tuple[str, list[str]]] = [
    (
        "第一章 稀缺与选择",
        [
            "稀缺性是指资源相对于人类欲望的有限性。",
            "机会成本是所放弃的最佳替代用途的价值。",
            "生产可能性边界展示了在资源约束下的选择与代价。",
            "经济学研究如何在稀缺条件下配置资源。",
        ],
    ),
    (
        "第二章 供给与需求",
        [
            "需求法则指出价格上升则需求量下降。",
            "供给法则描述价格与供给量的正向关系。",
            "均衡价格是供给曲线与需求曲线相交时形成的价格。",
            "过剩出现在价格高于均衡水平的时候。",
        ],
    ),
    (
        "第三章 弹性及其应用",
        [
            "需求价格弹性衡量需求量对价格变化的敏感程度。",
            "生活必需品的需求通常缺乏弹性。",
            "供给弹性在长期通常大于短期。",
            "农产品的价格波动可以用弹性不足来解释。",
        ],
    ),
    (
        "第四章 消费者选择",
        [
            "边际效用是指每增加一单位消费带来的效用增量。",
            "边际效用递减规律解释了需求曲线向下倾斜。",
            "消费者均衡发生在每元钱边际效用相等的时候。",
        ],
    ),
    (
        "第五章 市场失灵",
        [
            "外部性是指经济活动对第三方的影响未被定价。",
            "公共物品具有非排他性与非竞争性。",
            "信息不对称会导致逆向选择与道德风险。",
            "庇古税用于矫正负外部性。",
        ],
    ),
    (
        "第六章 宏观经济度量",
        [
            "国内生产总值度量一国境内的最终产品与劳务总值。",
            "GDP 平减指数用于剔除价格变动的影响。",
            "通货膨胀率衡量物价总水平的持续上涨。",
            "失业率统计劳动力中未就业且在寻找工作的比例。",
        ],
    ),
]

QUESTIONS_20 = [
    "稀缺性是什么意思",
    "机会成本的定义是什么",
    "生产可能性边界有什么用",
    "需求法则说了什么",
    "供给法则的内容是什么",
    "均衡价格怎么形成",
    "过剩什么时候出现",
    "需求价格弹性是什么",
    "生活必需品的弹性特点",
    "供给弹性的长期短期差异",
    "农产品价格波动怎么解释",
    "边际效用的含义",
    "边际效用递减规律解释了什么",
    "消费者均衡在什么条件下实现",
    "外部性指的是什么",
    "公共物品有哪些特性",
    "信息不对称导致什么问题",
    "庇古税是干什么用的",
    "国内生产总值怎么度量",
    "通货膨胀率衡量什么",
]

NO_BASIS_QUESTIONS = [
    "量子力学的测不准原理是什么",
    "拿破仑是在哪一年加冕的",
    "如何种植西红柿",
    "Python 的 GIL 是什么",
    "月亮的直径是多少公里",
    "相对论的质能方程怎么推导",
]


def _make_book(storage):
    from app.books.models import BookDoc, Chapter, DocMeta, Para, make_para_id

    chapters = [
        Chapter(
            id=f"c{idx:03d}",
            title=title,
            paras=[Para(id=make_para_id(idx, i), text=t) for i, t in enumerate(paras, 1)],
        )
        for idx, (title, paras) in enumerate(CHAPTERS, 1)
    ]
    doc = BookDoc(
        meta=DocMeta(bookId="b" * 16, title="合成经济学六讲", format="epub", fileHash="b" * 64),
        chapters=chapters,
    )
    storage.write_bookdoc(doc)
    return doc


@pytest.fixture(scope="module")
def qa_env(tmp_path_factory):
    from app.storage import Storage

    storage = Storage(tmp_path_factory.mktemp("m1"))
    storage.ensure_layout()
    doc = _make_book(storage)
    usage_log = UsageLog(storage)
    backend = MockLLMClient(usage_log, responder=mock_behaviors.dispatch)
    import asyncio

    asyncio.run(build_book_knowledge(storage, doc.meta.bookId, backend))
    return storage, usage_log, backend, doc


@pytest.mark.asyncio
async def test_20_cross_chapter_questions_all_citations_valid(qa_env) -> None:
    """T1.6.1：20 个跨章问题 → 引用出处 100% 真实可查。"""
    storage, usage_log, backend, doc = qa_env
    para_text = {p.id: p.text for ch in doc.chapters for p in ch.paras}
    asked = 0
    for question in QUESTIONS_20:
        result = await answer_question(
            storage, usage_log, backend, doc.meta.bookId, question, chapter_id="c001"
        )
        assert result.hasBasis, f"应有据回答：{question}（得到：{result.answer}）"
        assert result.citations, f"引用不得为空：{question}"
        for cite in result.citations:
            assert cite.paraId in para_text, f"paraId 不存在：{cite.paraId}"
            assert cite.quote in para_text[cite.paraId], (
                f"quote 与段落原文不符：{question} / {cite.paraId}"
            )
        asked += 1
    assert asked == 20


@pytest.mark.asyncio
async def test_no_basis_questions_all_refused(qa_env) -> None:
    """T1.6.2：无依据问题集 → 100% 明确回答「书中未涉及」。"""
    storage, usage_log, backend, doc = qa_env
    for question in NO_BASIS_QUESTIONS:
        result = await answer_question(
            storage, usage_log, backend, doc.meta.bookId, question, chapter_id="c001"
        )
        assert result.answer == "书中未涉及", f"应拒答：{question}（得到：{result.answer}）"
        assert result.citations == []
        assert result.hasBasis is False


@pytest.mark.asyncio
async def test_cross_chapter_retrieval_hits_right_chapter(qa_env) -> None:
    """跨章问题应装载正确章节的旁证（如弹性问题命中第三章）。"""
    storage, usage_log, backend, doc = qa_env
    result = await answer_question(
        storage, usage_log, backend, doc.meta.bookId, "全书怎么讲需求价格弹性", chapter_id="c001"
    )
    assert result.witnessUsed
    assert any(c.paraId.startswith("c003") for c in result.citations)
