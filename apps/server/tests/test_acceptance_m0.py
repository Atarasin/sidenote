"""M0 验收（计划 T0.5.1 自动化部分）：5 本合成测试书全链路解析验收。

上游 §6-M0 的数据面标准：
  - 解析成功、章/段结构完整、段落 ID 稳定（重复解析一致）
  - 目录 100% 可解析到真实章节（跳转准确率的数据前提）
  - 无乱码段落进上下文；EPUB 图片 / PDF 图表兜底截图落盘
真实书的人工翻页/选中/跳章实测清单见 docs/2026-09-02_M0解析缺陷清单.md。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

from app.books import parsing
from app.books.text_utils import is_garbled
from gen_test_books import gen_book1, gen_book2, gen_book3, gen_book4, gen_book5


def _ctx(tmp_path: Path, book_id: str = "abc0123456789abc") -> parsing.ParseContext:
    return parsing.ParseContext(
        book_id=book_id,
        file_hash="f" * 64,
        fallback_title="回退书名",
        figures_dir=tmp_path / "figures",
    )


GENS = [gen_book1, gen_book2, gen_book3, gen_book4, gen_book5]


@pytest.fixture(scope="module")
def five_books(tmp_path_factory) -> list[Path]:
    out = tmp_path_factory.mktemp("testbooks")
    for gen in GENS:
        gen(out)
    files = sorted(out.iterdir())
    assert len(files) == 5
    return files


@pytest.fixture(scope="module")
def parsed(five_books, tmp_path_factory) -> dict[str, object]:
    out: dict[str, object] = {}
    for path in five_books:
        fmt = "epub" if path.suffix == ".epub" else "pdf"
        ctx = _ctx(tmp_path_factory.mktemp(f"fig-{path.stem}"))
        doc = parsing.parse_book_file(path, fmt, ctx)
        out[path.name] = doc
    return out


def test_all_five_parse_with_content(parsed) -> None:
    assert len(parsed) == 5
    for name, doc in parsed.items():
        chapters = doc.chapters  # type: ignore[attr-defined]
        assert chapters, f"{name} 无章节"
        assert all(ch.paras for ch in chapters), f"{name} 存在空章节"
        all_paras = [p for ch in chapters for p in ch.paras]
        assert not any(is_garbled(p.text) for p in all_paras), f"{name} 存在乱码段落"


def test_epub_books_structure(parsed) -> None:
    b1 = parsed["经济学原理.epub"]
    assert len(b1.chapters) == 8  # type: ignore[attr-defined]
    assert len(b1.toc) == 8  # type: ignore[attr-defined]
    assert len(b1.figures) == 1  # type: ignore[attr-defined] —— 插图落盘
    assert any("2024" in p.text for ch in b1.chapters for p in ch.paras)  # type: ignore[attr-defined]

    b2 = parsed["货币银行学.epub"]
    assert len(b2.chapters) == 4  # type: ignore[attr-defined]
    sub = b2.toc[1].children[0]  # type: ignore[attr-defined]
    assert sub.title == "信用创造机制"
    assert sub.paraId and sub.paraId.startswith("c002-")  # 锚点小节命中第二章

    b3 = parsed["价格理论讲义.epub"]
    assert len(b3.chapters) == 2  # type: ignore[attr-defined]


def test_pdf_books_structure(parsed) -> None:
    b4 = parsed["宏观经济分析.pdf"]
    titles = [c.title for c in b4.chapters]  # type: ignore[attr-defined]
    assert any("增长与波动" in t for t in titles), titles
    assert len(b4.figures) >= 1  # type: ignore[attr-defined] —— 插图页兜底截图
    # 段落带页码（渲染层跳转依据）
    assert all(p.page is not None for ch in b4.chapters for p in ch.paras)  # type: ignore[attr-defined]

    b5 = parsed["计量经济学导论.pdf"]
    assert next(c.title for c in b5.chapters) == "第一章 经典线性回归"  # type: ignore[attr-defined]
    texts = [p.text for ch in b5.chapters for p in ch.paras]  # type: ignore[attr-defined]
    joined = "｜".join(texts)
    # 双栏按栏序：第一页左栏 L00 前于右栏 R00
    assert joined.index("L00") < joined.index("R00")


def test_toc_resolves_100pct(parsed) -> None:
    """目录跳转准确率 100% 的数据前提：每个 toc 项都指向真实存在的章节。"""
    for name, doc in parsed.items():
        chapter_ids = {c.id for c in doc.chapters}  # type: ignore[attr-defined]
        stack = list(doc.toc)  # type: ignore[attr-defined]
        count = 0
        while stack:
            item = stack.pop()
            if item.children:
                stack.extend(item.children)
            assert item.chapterId in chapter_ids, f"{name} 目录项 {item.title} 指向不存在的章节"
            count += 1
        assert count >= 1


def test_repeat_parse_deterministic(five_books, tmp_path) -> None:
    """T0.2.2：同书重复解析结果一致。"""
    path = five_books[0]
    d1 = parsing.parse_book_file(path, "epub", _ctx(tmp_path / "a"))
    d2 = parsing.parse_book_file(path, "epub", _ctx(tmp_path / "b"))
    assert d1.model_dump_json() == d2.model_dump_json()


def test_upload_all_five_via_api(client, five_books) -> None:
    """上传链路端到端：5 本书全部 success 且 bookdoc 可取。"""
    for path in five_books:
        with path.open("rb") as fh:
            resp = client.post("/api/books", files={"file": (path.name, fh)})
        assert resp.status_code == 201
        meta = resp.json()
        refreshed = client.get(f"/api/books/{meta['bookId']}").json()
        assert refreshed["parseStatus"] == "success", f"{path.name}: {refreshed.get('parseError')}"
        doc = client.get(f"/api/books/{meta['bookId']}/bookdoc").json()
        assert doc["chapters"]
