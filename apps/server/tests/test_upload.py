"""上传接口（计划 T0.1.3 + T0.2.6）：落盘、格式校验、哈希去重入口、解析状态流转。"""

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


def test_upload_epub_parses_to_success(client, storage, tiny_epub) -> None:
    resp = _upload(client, tiny_epub)
    assert resp.status_code == 201
    meta = resp.json()
    assert meta["format"] == "epub"
    assert len(meta["bookId"]) == 16

    # 原文件落盘
    source = storage.source_path(meta["bookId"], "epub")
    assert source.is_file()
    assert Storage.sha256_file(source) == meta["fileHash"]

    # 后台解析完成：状态 success，元数据来自书内
    refreshed = client.get(f"/api/books/{meta['bookId']}").json()
    assert refreshed["parseStatus"] == "success", refreshed.get("parseError")
    assert refreshed["title"] == "极小经济学（测试用书）"
    assert refreshed["parasCount"] == 3

    # bookdoc 可得，且段落 ID 稳定（c001-p0001 起）
    doc = client.get(f"/api/books/{meta['bookId']}/bookdoc").json()
    assert [p["id"] for p in doc["chapters"][0]["paras"]] == [
        "c001-p0001",
        "c001-p0002",
        "c001-p0003",
    ]
    assert doc["toc"] and doc["toc"][0]["chapterId"] == "c001"


def test_upload_broken_pdf_marks_failed(client, tiny_pdf) -> None:
    resp = _upload(client, tiny_pdf)
    assert resp.status_code == 201
    meta = resp.json()
    refreshed = client.get(f"/api/books/{meta['bookId']}").json()
    assert refreshed["parseStatus"] == "failed"
    assert refreshed["parseError"]
    # 解析失败时 bookdoc 不可得（409 而非 404：书存在但未就绪）
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
    first = _upload(client, tiny_epub).json()
    second = _upload(client, tiny_epub).json()
    assert first["bookId"] == second["bookId"]
    books = client.get("/api/books").json()
    assert len(books) == 1


def test_get_missing_book_404(client) -> None:
    assert client.get("/api/books/" + "0" * 16).status_code == 404
