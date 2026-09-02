"""存储布局（计划 T0.1.2）与 meta/bookdoc 读写。"""

from __future__ import annotations

import json

from app.storage import Storage, utc_now_iso


def test_ensure_layout_creates_dirs(storage: Storage) -> None:
    assert (storage.root / "books").is_dir()
    assert (storage.root / "usage").is_dir()
    assert (storage.root / "sessions").is_dir()
    assert (storage.root / "tmp").is_dir()


def test_layout_paths(storage: Storage) -> None:
    book = "a" * 16
    assert storage.source_path(book, "epub") == storage.root / "books" / book / "source.epub"
    assert storage.meta_path(book).name == "meta.json"
    assert storage.bookdoc_path(book).name == "bookdoc.json"
    assert storage.figures_dir(book).name == "figures"
    assert storage.knowledge_dir(book).name == "knowledge"  # M1 摘要/向量索引
    assert storage.diagrams_dir(book).name == "diagrams"  # M2 图解缓存
    assert storage.usage_log_path() == storage.root / "usage" / "calls.jsonl"  # M1 计费日志


def test_sha256_and_book_id(tmp_path) -> None:
    p = tmp_path / "f.bin"
    p.write_bytes(b"hello sidenote")
    h1 = Storage.sha256_file(p)
    assert h1 == Storage.sha256_file(p)
    assert Storage.book_id_for(h1) == h1[:16]
    assert len(Storage.book_id_for(h1)) == 16


def test_meta_roundtrip_and_list(storage: Storage) -> None:
    from app.books.models import BookFileMeta

    meta = BookFileMeta(
        bookId="b" * 16,
        title="测试书",
        format="epub",
        fileHash="b" * 64,
        fileName="测试书.epub",
        sizeBytes=123,
        addedAt=utc_now_iso(),
    )
    storage.write_meta(meta)
    loaded = storage.read_meta("b" * 16)
    assert loaded == meta
    assert storage.read_meta("c" * 16) is None
    assert [m.bookId for m in storage.list_books()] == ["b" * 16]

    # JSON 字段名与共享类型一致（camelCase）
    raw = json.loads(storage.meta_path("b" * 16).read_text(encoding="utf-8"))
    assert set(raw) >= {"bookId", "parseStatus", "chaptersCount"}
