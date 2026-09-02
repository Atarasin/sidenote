"""本地存储布局（计划 T0.1.2）：

data/
  books/<bookId>/
    source.{epub|pdf}     # 书籍原文件（红线 1：只存本地）
    meta.json             # 上传与解析状态
    bookdoc.json          # 解析产物 BookDoc
    figures/              # 抽取/兜底的图片
    knowledge/            # M1：全书摘要、目录地图、术语表、向量索引
    diagrams/             # M2：图解缓存
  usage/calls.jsonl       # M1：模型调用日志与计费统计
  sessions/              # M2：会话频率限制状态
  tmp/                   # 上传临时文件
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from .books.models import BookDoc, BookFileMeta


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Storage:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    # ---- 目录结构 ----
    def ensure_layout(self) -> None:
        for sub in ("books", "usage", "sessions", "tmp"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)

    def book_dir(self, book_id: str) -> Path:
        return self.root / "books" / book_id

    def source_path(self, book_id: str, fmt: str) -> Path:
        return self.book_dir(book_id) / f"source.{fmt}"

    def meta_path(self, book_id: str) -> Path:
        return self.book_dir(book_id) / "meta.json"

    def bookdoc_path(self, book_id: str) -> Path:
        return self.book_dir(book_id) / "bookdoc.json"

    def figures_dir(self, book_id: str) -> Path:
        return self.book_dir(book_id) / "figures"

    def knowledge_dir(self, book_id: str) -> Path:
        return self.book_dir(book_id) / "knowledge"

    def diagrams_dir(self, book_id: str) -> Path:
        return self.book_dir(book_id) / "diagrams"

    def tmp_dir(self) -> Path:
        return self.root / "tmp"

    def usage_log_path(self) -> Path:
        return self.root / "usage" / "calls.jsonl"

    # ---- 文件哈希与 bookId ----
    @staticmethod
    def sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def book_id_for(file_hash: str) -> str:
        return file_hash[:16]

    # ---- meta.json ----
    def read_meta(self, book_id: str) -> BookFileMeta | None:
        path = self.meta_path(book_id)
        if not path.exists():
            return None
        return BookFileMeta.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def write_meta(self, meta: BookFileMeta) -> None:
        path = self.meta_path(meta.bookId)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(meta.model_dump_json(indent=2), encoding="utf-8")

    def list_books(self) -> list[BookFileMeta]:
        books_dir = self.root / "books"
        if not books_dir.exists():
            return []
        metas = []
        for entry in sorted(books_dir.iterdir()):
            if entry.is_dir():
                meta = self.read_meta(entry.name)
                if meta is not None:
                    metas.append(meta)
        metas.sort(key=lambda m: m.addedAt, reverse=True)
        return metas

    # ---- bookdoc.json ----
    def read_bookdoc(self, book_id: str) -> BookDoc | None:
        path = self.bookdoc_path(book_id)
        if not path.exists():
            return None
        return BookDoc.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def write_bookdoc(self, doc: BookDoc) -> None:
        path = self.bookdoc_path(doc.meta.bookId)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(doc.model_dump_json(indent=2), encoding="utf-8")
