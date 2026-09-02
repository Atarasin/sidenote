"""全书理解构建（计划 Slice 1.2 / 上游 §3.2 常驻部分）。

- 每章摘要 200~400 字（T1.2.1），与目录地图、术语表一起组成常驻上下文包（T1.2.2）。
- 同书只构建一次：knowledge.json 存在且无失败章时直接返回（T1.2.1）。
- 单章失败可重试、可跳过并标记，不阻塞整书（T1.2.3）：failedChapters 记录，
  rebuild(retry_failed=True) 只重跑失败章。
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

from ..llm.errors import ModelError
from ..llm.types import ChatMessage
from .models import (
    BookKnowledge,
    ChapterSummary,
    GlossaryTerm,
    load_knowledge,
    save_knowledge,
)

SUMMARY_SYSTEM = (
    "你是学术阅读助理。请为给定章节写一段 200~400 字的中文摘要，"
    "覆盖章节的核心概念与论证脉络，只依据原文，不要编造。直接输出摘要正文。"
)
GLOSSARY_SYSTEM = (
    "你是学术阅读助理。请从给定章节中提取 3~8 个关键术语及一句话定义，"
    '只输出 JSON 数组：[{"term":"术语","definition":"定义句"}]，定义必须来自原文句子。'
)


def _chapter_messages(
    system: str, book_title: str, chapter_title: str, body: str
) -> list[ChatMessage]:
    return [
        ChatMessage("system", system),
        ChatMessage(
            "user",
            f"书名：{book_title}\n章节：{chapter_title}\n【章节内容】\n{body}\n【/章节内容】",
        ),
    ]


async def build_book_knowledge(
    storage,
    book_id: str,
    backend,
    *,
    retry_failed: bool = False,
) -> BookKnowledge:
    doc = storage.read_bookdoc(book_id)
    if doc is None:
        raise FileNotFoundError(f"书籍未解析：{book_id}")

    existing = load_knowledge(storage, book_id)
    if existing and existing.complete:
        return existing  # 同书只构建一次
    knowledge = existing or BookKnowledge(
        bookId=book_id, builtAt=datetime.now(UTC).isoformat(timespec="seconds")
    )

    for chapter in doc.chapters:
        if not _needs_build(chapter.id, knowledge, retry_failed):
            continue
        body = "\n".join(p.text for p in chapter.paras)
        if not body.strip():
            _mark_failed(knowledge, chapter.id, chapter.title)
            continue
        try:
            summary = await _summarize(backend, book_id, doc.meta.title, chapter.title, body)
            terms = await _extract_terms(backend, book_id, doc.meta.title, chapter.title, body)
        except ModelError:
            _mark_failed(knowledge, chapter.id, chapter.title)  # 单章失败不阻塞整书（T1.2.3）
            continue
        _upsert(
            knowledge, ChapterSummary(chapterId=chapter.id, title=chapter.title, summary=summary)
        )
        knowledge.glossary = [t for t in knowledge.glossary if t.chapterId != chapter.id]
        knowledge.glossary.extend(
            GlossaryTerm(term=it["term"], definition=it["definition"], chapterId=chapter.id)
            for it in terms
        )

    knowledge.failedChapters = [c.chapterId for c in knowledge.chapters if c.status == "failed"]
    knowledge.tocMap = [
        f"{c.title}：{_one_line(c.summary)}" for c in knowledge.chapters if c.status == "ok"
    ]
    knowledge.builtAt = datetime.now(UTC).isoformat(timespec="seconds")
    knowledge.provider = getattr(backend, "provider", "")
    save_knowledge(storage, knowledge)
    return knowledge


def _needs_build(chapter_id: str, knowledge: BookKnowledge, retry_failed: bool) -> bool:
    record = next((c for c in knowledge.chapters if c.chapterId == chapter_id), None)
    if record is None:
        return True
    return record.status == "failed" and retry_failed  # 失败章仅在显式重试时重跑


def _mark_failed(knowledge: BookKnowledge, chapter_id: str, title: str) -> None:
    _upsert(
        knowledge,
        ChapterSummary(chapterId=chapter_id, title=title, summary="", status="failed"),
    )


def _upsert(knowledge: BookKnowledge, record: ChapterSummary) -> None:
    knowledge.chapters = [c for c in knowledge.chapters if c.chapterId != record.chapterId]
    knowledge.chapters.append(record)


async def _summarize(backend, book_id: str, book_title: str, chapter_title: str, body: str) -> str:
    result = await backend.chat(
        "long_text_qa",
        _chapter_messages(SUMMARY_SYSTEM, book_title, chapter_title, body),
        book_id=book_id,
        purpose="chapter_summary",
    )
    return _finalize_summary(result.content)


async def _extract_terms(
    backend, book_id: str, book_title: str, chapter_title: str, body: str
) -> list[dict]:
    result = await backend.chat(
        "long_text_qa",
        _chapter_messages(GLOSSARY_SYSTEM, book_title, chapter_title, body),
        book_id=book_id,
        purpose="glossary",
    )
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", result.content.strip())
    try:
        data = json.loads(content)
        if isinstance(data, list):
            return [
                {
                    "term": str(it.get("term", ""))[:40],
                    "definition": str(it.get("definition", ""))[:200],
                }
                for it in data
                if it.get("term")
            ]
    except (json.JSONDecodeError, AttributeError):
        pass
    return []


def _finalize_summary(text: str) -> str:
    text = text.strip()
    return text[:400]


def _one_line(summary: str) -> str:
    line = summary.replace("\n", " ").strip()
    return line[:60] + ("…" if len(line) > 60 else "")
