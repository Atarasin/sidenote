"""EPUB 解析器（计划 T0.2.3 / T0.2.2）：章节、段落、目录、图片、稳定性。"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.books import parsing
from app.books.epub_parser import parse_epub
from app.books.models import BookDoc

from epub_fixture import build_epub

CH1 = {
    "file_name": "ch1.xhtml",
    "title": "第一章 供给与需求",
    "html": (
        "<html><head><title>第一章</title></head><body>"
        "<h1 id='h1'>第一章 供给与需求</h1>"
        "<p id='p1'>供给与需求是经济学最基本的一对概念。</p>"
        "<p>当供给曲线与需求曲线相交时，市场出清，形成均衡价格。</p>"
        "<blockquote>价格像一只看不见的手，协调着买卖双方。</blockquote>"
        "<table><tr><th>年份</th><th>均价</th></tr><tr><td>2024</td><td>30 元</td></tr></table>"
        "</body></html>"
    ),
}
CH2 = {
    "file_name": "ch2.xhtml",
    "title": "第二章 弹性",
    "html": (
        "<html><head><title>第二章</title></head><body>"
        "<h1>第二章 弹性</h1>"
        "<p id='elastic'>需求价格弹性衡量需求量对价格变化的敏感程度。</p>"
        "<p>生活必需品的需求通常缺乏弹性。</p>"
        "</body></html>"
    ),
}


@pytest.fixture
def ctx(tmp_path: Path) -> parsing.ParseContext:
    return parsing.ParseContext(
        book_id="a" * 16,
        file_hash="a" * 64,
        fallback_title="回退书名",
        figures_dir=tmp_path / "figures",
    )


def _two_chapter_epub(tmp_path: Path) -> Path:
    from ebooklib import epub

    toc = (
        (
            epub.Section("第一章 供给与需求", href="ch1.xhtml"),
            (epub.Link("ch2.xhtml#elastic", "弹性的定义", "sec2-1"),),
        ),
        epub.Link("ch2.xhtml", "第二章 弹性", "ch2"),
    )
    return build_epub(tmp_path / "book.epub", chapters=[CH1, CH2], toc=toc)


def test_epub_chapters_and_paras(tmp_path, ctx) -> None:
    doc = parse_epub(_two_chapter_epub(tmp_path), ctx)
    assert doc.meta.title == "经济学入门（测试书）"
    assert doc.meta.authors == ["测试作者"]
    assert [c.id for c in doc.chapters] == ["c001", "c002"]
    assert [p.id for p in doc.chapters[0].paras] == [
        "c001-p0001",
        "c001-p0002",
        "c001-p0003",
        "c001-p0004",
        "c001-p0005",
    ]
    assert doc.chapters[0].paras[0].text == "第一章 供给与需求"  # h1 作为段落（锚点载体）
    assert doc.chapters[0].paras[1].text.startswith("供给与需求是经济学")
    # 表格退化为单段文本
    table_text = doc.chapters[0].paras[4].text
    assert "2024" in table_text and "均价" in table_text


def test_epub_toc_tree_with_anchor(tmp_path, ctx) -> None:
    doc = parse_epub(_two_chapter_epub(tmp_path), ctx)
    top_titles = [t.title for t in doc.toc]
    assert top_titles == ["第一章 供给与需求", "第二章 弹性"]
    first = doc.toc[0]
    assert first.chapterId == "c001"
    child = first.children[0]
    assert child.title == "弹性的定义"
    assert child.chapterId == "c002"
    assert child.paraId == "c002-p0002"  # 锚点 #elastic 命中第二段（首段是章标题 h1）


def test_epub_repeat_parse_is_identical(tmp_path, ctx) -> None:
    """T0.2.2 稳定段落 ID：同文件重复解析结果完全一致。"""
    path = _two_chapter_epub(tmp_path)
    first: BookDoc = parse_epub(path, ctx)
    second: BookDoc = parse_epub(path, ctx)
    assert first.model_dump_json() == second.model_dump_json()


def test_epub_image_extracted_as_figure(tmp_path, ctx) -> None:
    html = (
        "<html><body><h1>插图章</h1>"
        "<figure><img src='images/fig1.png' alt='供需曲线图'/>"
        "<figcaption>图 1 供需均衡</figcaption></figure>"
        "<p>如图所示，交点即均衡。</p></body></html>"
    )
    path = build_epub(
        tmp_path / "img.epub",
        chapters=[{"file_name": "ch1.xhtml", "title": "插图章", "html": html}],
        with_image=True,
    )
    doc = parse_epub(path, ctx)
    assert len(doc.figures) == 1
    fig = doc.figures[0]
    assert fig.chapterId == "c001"
    assert fig.caption == "图 1 供需均衡"
    assert (tmp_path / "figures" / Path(fig.imgPath).name).is_file()


def test_epub_broken_file_raises(tmp_path, ctx) -> None:
    bad = tmp_path / "bad.epub"
    bad.write_bytes(b"PK\x03\x04 not a real epub")
    with pytest.raises(parsing.ParseError):
        parse_epub(bad, ctx)


def test_epub_no_content_raises(tmp_path, ctx) -> None:
    html = "<html><body><p></p></body></html>"
    path = build_epub(
        tmp_path / "empty.epub",
        chapters=[{"file_name": "ch1.xhtml", "title": "空", "html": html}],
    )
    with pytest.raises(parsing.ParseError):
        parse_epub(path, ctx)
