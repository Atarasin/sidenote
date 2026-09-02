"""全书理解产物（上游 §3.2 常驻上下文）的模型与持久化。"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field


class ChapterSummary(BaseModel):
    chapterId: str
    title: str
    summary: str
    status: Literal["ok", "failed"] = "ok"


class GlossaryTerm(BaseModel):
    term: str
    definition: str
    chapterId: str = ""


class BookKnowledge(BaseModel):
    """knowledge/knowledge.json：同书只构建一次（计划 T1.2.1）。"""

    bookId: str
    chapters: list[ChapterSummary] = Field(default_factory=list)
    tocMap: list[str] = Field(default_factory=list)  # 目录地图：每章一行「标题：一句话」
    glossary: list[GlossaryTerm] = Field(default_factory=list)
    failedChapters: list[str] = Field(default_factory=list)
    builtAt: str = ""
    provider: str = ""

    @property
    def complete(self) -> bool:
        return bool(self.chapters) and not self.failedChapters


def knowledge_path(storage, book_id: str):
    return storage.knowledge_dir(book_id) / "knowledge.json"


def load_knowledge(storage, book_id: str) -> BookKnowledge | None:
    path = knowledge_path(storage, book_id)
    if not path.exists():
        return None
    return BookKnowledge.model_validate(json.loads(path.read_text(encoding="utf-8")))


def save_knowledge(storage, knowledge: BookKnowledge) -> None:
    path = knowledge_path(storage, knowledge.bookId)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(knowledge.model_dump_json(indent=2), encoding="utf-8")
