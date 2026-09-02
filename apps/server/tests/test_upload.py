"""上传接口（计划 T0.1.3）：落盘、格式校验、哈希去重入口、解析状态流转。

Slice 0.1 阶段解析器尚未注册（Slice 0.2 落地），故上传后状态为 failed（诚实状态，不静默）。
"""

from __future__ import annotations

from app.storage import Storage


def _upload(client, path, name=None):
    with path.open("rb") as fh:
        return client.post(
            "/api/books", files={"file": (name or path.name, fh, "application/octet-stream")}
        )


def test_health(client) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_upload_epub_lands_and_records_parse_failure(client, storage, tiny_epub) -> None:
    resp = _upload(client, tiny_epub)
    assert resp.status_code == 201
    meta = resp.json()
    assert meta["format"] == "epub"
    assert len(meta["bookId"]) == 16

    # 原文件落盘
    source = storage.source_path(meta["bookId"], "epub")
    assert source.is_file()
    assert Storage.sha256_file(source) == meta["fileHash"]

    # Slice 0.1 无解析器 → failed（Slice 0.2 接入后此断言更新）
    refreshed = client.get(f"/api/books/{meta['bookId']}").json()
    assert refreshed["parseStatus"] == "failed"
    assert "解析器尚未注册" in refreshed["parseError"]

    # bookdoc 在解析成功前不可得
    assert client.get(f"/api/books/{meta['bookId']}/bookdoc").status_code == 409


def test_upload_rejects_unsupported_format(client, tmp_path) -> None:
    p = tmp_path / "book.txt"
    p.write_text("not a book")
    resp = _upload(client, p)
    assert resp.status_code == 400


def test_upload_rejects_empty_file(client, tmp_path) -> None:
    p = tmp_path / "empty.epub"
    p.write_bytes(b"")
    resp = _upload(client, p)
    assert resp.status_code == 400


def test_upload_pdf_detected_by_header(client, tmp_path) -> None:
    p = tmp_path / "noext"
    p.write_bytes(b"%PDF-1.7 fake")
    resp = _upload(client, p, name="book.pdf")
    assert resp.status_code == 201
    assert resp.json()["format"] == "pdf"


def test_upload_same_file_dedupes(client, tiny_epub) -> None:
    first = _upload(client, tiny_epub)
    second = _upload(client, tiny_epub)
    assert first.json()["bookId"] == second.json()["bookId"]


def test_get_missing_book_404(client) -> None:
    assert client.get("/api/books/" + "0" * 16).status_code == 404
