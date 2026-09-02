"""测试夹具：隔离的 Storage / TestClient / 最小合法书籍文件。"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from app.main import create_app
from app.storage import Storage
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    s = Storage(tmp_path / "data")
    s.ensure_layout()
    return s


@pytest.fixture
def client(storage: Storage) -> TestClient:
    return TestClient(create_app(storage=storage))


@pytest.fixture
def tiny_epub(tmp_path: Path) -> Path:
    """最小合法 EPUB：mimetype + container.xml + content.opf + 一章 XHTML。"""
    path = tmp_path / "tiny.epub"
    container = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""
    opf = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="uid">urn:uuid:0f8c1e2a-test-0001</dc:identifier>
    <dc:title>极小经济学（测试用书）</dc:title>
    <dc:creator>测试作者</dc:creator>
    <dc:language>zh</dc:language>
  </metadata>
  <manifest>
    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
  </manifest>
  <spine><itemref idref="ch1"/></spine>
</package>"""
    ch1 = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>第一章</title></head>
<body><h1>第一章 供给与需求</h1>
<p>供给与需求是经济学最基本的两个概念。</p>
<p>均衡价格由市场自发形成。</p></body></html>"""
    nav = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>目录</title></head><body>
<nav epub:type="toc" id="toc"><ol><li><a href="ch1.xhtml">第一章 供给与需求</a></li></ol></nav>
</body></html>"""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", container)
        zf.writestr("OEBPS/content.opf", opf)
        zf.writestr("OEBPS/ch1.xhtml", ch1)
        zf.writestr("OEBPS/nav.xhtml", nav)
    return path


@pytest.fixture
def tiny_pdf(tmp_path: Path) -> Path:
    """最小 PDF（仅文件头 + 尾标记，供上传链路测试；解析测试用 PyMuPDF 生成真实文档）。"""
    path = tmp_path / "tiny.pdf"
    path.write_bytes(
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"trailer<</Root 1 0 R>>\n%%EOF"
    )
    return path
