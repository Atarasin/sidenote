"""BookDoc 与书籍元数据的 pydantic 模型（与 shared/types/bookdoc.schema.json 一致）。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

BOOK_ID_PATTERN = r"^[0-9a-f]{16}$"
CHAPTER_ID_PATTERN = r"^c\d{3,}$"
PARA_ID_PATTERN = r"^c\d{3,}-p\d{4,}$"


def make_chapter_id(ch_index: int) -> str:
    """章节序（1 起）→ 章节 ID。同一本书重复解析结果一致（计划 T0.2.2）。"""
    return f"c{ch_index:03d}"


def make_para_id(ch_index: int, para_index: int) -> str:
    """章节序 + 段序（均 1 起）→ 段落 ID。"""
    return f"c{ch_index:03d}-p{para_index:04d}"


class DocMeta(BaseModel):
    bookId: str = Field(pattern=BOOK_ID_PATTERN)
    title: str = Field(min_length=1)
    authors: list[str] = Field(default_factory=list)
    format: Literal["epub", "pdf"]
    fileHash: str = Field(min_length=8)


class TocItem(BaseModel):
    id: str = Field(min_length=1)
    title: str
    chapterId: str | None = None
    paraId: str | None = None
    children: list[TocItem] = Field(default_factory=list)


class Para(BaseModel):
    id: str = Field(pattern=PARA_ID_PATTERN)
    text: str
    page: int | None = None  # PDF 专用：段落首字符所在页（0 起）


class Chapter(BaseModel):
    id: str = Field(pattern=CHAPTER_ID_PATTERN)
    title: str
    paras: list[Para] = Field(default_factory=list)


class Figure(BaseModel):
    id: str = Field(min_length=1)
    chapterId: str
    imgPath: str
    caption: str = ""


class BookDoc(BaseModel):
    meta: DocMeta
    toc: list[TocItem] = Field(default_factory=list)
    chapters: list[Chapter] = Field(default_factory=list)
    figures: list[Figure] = Field(default_factory=list)


ParseStatus = Literal["pending", "parsing", "success", "failed"]


class BookFileMeta(BaseModel):
    """data/books/<id>/meta.json：上传记录与解析状态。"""

    bookId: str = Field(pattern=BOOK_ID_PATTERN)
    title: str  # 解析前为文件名主干，解析后为书名
    format: Literal["epub", "pdf"]
    fileHash: str
    fileName: str
    sizeBytes: int
    addedAt: str
    parseStatus: ParseStatus = "pending"
    parseError: str | None = None
    chaptersCount: int = 0
    parasCount: int = 0
