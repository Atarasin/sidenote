"""解析结果落盘缓存（计划 T0.2.6）：同文件哈希不重复解析。"""

from __future__ import annotations

from app.books import parsing
from app.books.routes import run_parse


def _upload(client, path, name):
    resp = client.post(
        "/api/books", files={"file": (name, path.open("rb"), "application/octet-stream")}
    )
    book_id = resp.json()["bookId"]
    # 后台解析任务在响应之后执行，取最新状态
    return client.get(f"/api/books/{book_id}").json()


def test_reparse_of_parsed_book_is_noop(client, storage, tiny_epub, monkeypatch) -> None:
    meta = _upload(client, tiny_epub, "t.epub")
    assert meta["parseStatus"] == "success"

    def sentinel(path, ctx):
        raise AssertionError("已解析成功的书不应重复解析")

    monkeypatch.setitem(parsing.PARSERS, "epub", sentinel)
    run_parse(storage, meta["bookId"])  # type: ignore[arg-type]
    refreshed = storage.read_meta(meta["bookId"])
    assert refreshed is not None and refreshed.parseStatus == "success"


def test_dedup_upload_does_not_reparse(client, storage, tiny_epub, monkeypatch) -> None:
    first = _upload(client, tiny_epub, "t.epub")

    calls: list[str] = []
    original = parsing.PARSERS["epub"]

    def counting(path, ctx):
        calls.append(ctx.book_id)
        return original(path, ctx)

    monkeypatch.setitem(parsing.PARSERS, "epub", counting)
    second = _upload(client, tiny_epub, "t.epub")
    assert second["bookId"] == first["bookId"]
    assert calls == []  # 命中入口侧去重，解析器根本没被调用


def test_failed_book_can_reparse(client, storage, tiny_pdf, monkeypatch) -> None:
    """解析失败（如损坏 PDF）不永久卡死：修复后可重试。"""
    meta = _upload(client, tiny_pdf, "t.pdf")
    assert meta["parseStatus"] == "failed"

    monkeypatch.setitem(parsing.PARSERS, "pdf", lambda path, ctx: _minimal_doc(ctx))
    run_parse(storage, meta["bookId"])  # type: ignore[arg-type]
    refreshed = storage.read_meta(meta["bookId"])
    assert refreshed is not None and refreshed.parseStatus == "success"
    assert storage.read_bookdoc(meta["bookId"]) is not None


def _minimal_doc(ctx):
    from app.books.models import BookDoc, Chapter, DocMeta, Para

    return BookDoc(
        meta=DocMeta(bookId=ctx.book_id, title="修复之书", format="pdf", fileHash=ctx.file_hash),
        chapters=[Chapter(id="c001", title="第一章", paras=[Para(id="c001-p0001", text="正文")])],
    )
