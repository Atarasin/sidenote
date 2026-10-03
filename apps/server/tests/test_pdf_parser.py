"""文字版 PDF 解析器（计划 T0.2.4 / T0.2.5）：阅读顺序、段落重组、章节、图表兜底、扫描版拒绝。"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.books import parsing
from app.books.pdf_parser import parse_pdf

from epub_fixture import tiny_png_bytes


@pytest.fixture
def ctx(tmp_path: Path) -> parsing.ParseContext:
    return parsing.ParseContext(
        book_id="b" * 16,
        file_hash="b" * 64,
        fallback_title="回退书名.pdf",
        figures_dir=tmp_path / "figures",
    )


def _new_doc():
    import fitz

    return fitz.open()


def _line(page, x: float, y: float, text: str, size: float = 11.0) -> None:
    page.insert_text((x, y), text, fontname="china-s", fontsize=size)


def test_pdf_single_column_paragraphs(tmp_path, ctx) -> None:
    doc = _new_doc()
    page = doc.new_page()
    _line(page, 60, 80, "需求法则指出，在其他条件不变时，价格上升则需求量下降。", 11)
    _line(page, 60, 98, "这一法则在绝大多数商品市场上成立。", 11)
    # 大间距 → 新段落
    _line(page, 60, 160, "供给法则则描述了价格与供给量之间的正向关系。", 11)
    path = tmp_path / "single.pdf"
    doc.save(str(path))

    parsed = parse_pdf(path, ctx)
    assert len(parsed.chapters) == 1
    paras = parsed.chapters[0].paras
    texts = [p.text for p in paras]
    assert any("需求法则" in t and "正向关系" not in t for t in texts)  # 前两行合为一段
    joined = "".join(texts)
    assert "需求法则" in joined and "供给法则" in joined
    assert all(p.page == 0 for p in paras)


def test_pdf_double_column_reading_order(tmp_path, ctx) -> None:
    doc = _new_doc()
    page = doc.new_page()  # A4 595 宽
    # 左栏 x=50，右栏 x=320；左栏 y 低于右栏起始也不得插队
    _line(page, 50, 100, "左栏第一句：供给曲线向右上方倾斜。", 11)
    _line(page, 50, 130, "左栏第二句：生产成本上升会推高供给价格。", 11)
    _line(page, 50, 160, "左栏第三句：技术进步使供给曲线右移。", 11)
    _line(page, 50, 190, "左栏第四句：均衡在供需相交处达成。", 11)
    _line(page, 320, 100, "右栏第一句：弹性衡量反应程度。", 11)
    _line(page, 320, 130, "右栏第二句：替代品越多弹性越大。", 11)
    _line(page, 320, 160, "右栏第三句：时间跨度越长弹性越足。", 11)
    _line(page, 320, 190, "右栏第四句：奢侈品弹性通常较高。", 11)
    path = tmp_path / "double.pdf"
    doc.save(str(path))

    parsed = parse_pdf(path, ctx)
    texts = [p.text for p in parsed.chapters[0].paras]
    joined = "｜".join(texts)
    assert joined.index("左栏第一句") < joined.index("右栏第一句")
    assert joined.index("左栏第四句") < joined.index("右栏第一句")  # 栏序优先于 y 序


def test_pdf_chapters_by_toc(tmp_path, ctx) -> None:
    doc = _new_doc()
    p1 = doc.new_page()
    _line(p1, 60, 80, "第一章 供给", 18)
    _line(p1, 60, 110, "供给是生产者愿意并能够出售的商品量。", 11)
    p2 = doc.new_page()
    _line(p2, 60, 80, "第二章 需求", 18)
    _line(p2, 60, 110, "需求是消费者愿意并能够购买的商品量。", 11)
    doc.set_toc([[1, "第一章 供给", 1], [1, "第二章 需求", 2]])
    path = tmp_path / "toc.pdf"
    doc.save(str(path))

    parsed = parse_pdf(path, ctx)
    assert [c.title for c in parsed.chapters] == ["第一章 供给", "第二章 需求"]
    assert [c.id for c in parsed.chapters] == ["c001", "c002"]
    # 章标题行作为首段保留（与 EPUB 的 h1 行为一致），正文紧随其后
    assert parsed.chapters[0].paras[0].text == "第一章 供给"
    assert "供给是生产者" in parsed.chapters[0].paras[1].text
    assert [t.title for t in parsed.toc] == ["第一章 供给", "第二章 需求"]
    assert parsed.chapters[1].paras[0].page == 1


def test_pdf_chapters_by_font_when_no_toc(tmp_path, ctx) -> None:
    doc = _new_doc()
    page = doc.new_page()
    _line(page, 60, 80, "第一章 生产可能性边界", 18)
    _line(page, 60, 110, "稀缺性是经济学的起点。", 11)
    _line(page, 60, 130, "生产可能性边界展示了选择与代价。", 11)
    _line(page, 60, 260, "第二章 机会成本", 18)
    _line(page, 60, 290, "机会成本是所放弃的最佳替代用途的价值。", 11)
    path = tmp_path / "font.pdf"
    doc.save(str(path))

    parsed = parse_pdf(path, ctx)
    titles = [c.title for c in parsed.chapters]
    assert "第一章 生产可能性边界" in titles and "第二章 机会成本" in titles
    ch2 = next(c for c in parsed.chapters if c.title == "第二章 机会成本")
    assert any("机会成本是所放弃" in p.text for p in ch2.paras)


def test_pdf_image_extracted_as_figure(tmp_path, ctx) -> None:
    import fitz

    doc = _new_doc()
    page = doc.new_page()
    _line(page, 60, 80, "下图为供需均衡示意图，展示了交点如何形成。", 11)
    page.insert_image(fitz.Rect(60, 120, 320, 320), stream=tiny_png_bytes())
    path = tmp_path / "img.pdf"
    doc.save(str(path))

    parsed = parse_pdf(path, ctx)
    assert len(parsed.figures) >= 1
    fig = parsed.figures[0]
    assert fig.imgPath.startswith("figures/")
    assert (tmp_path / "figures" / Path(fig.imgPath).name).is_file()
    assert fig.chapterId.startswith("c")


def test_pdf_scanned_rejected(tmp_path, ctx) -> None:
    import fitz

    doc = _new_doc()
    page = doc.new_page()
    page.insert_image(fitz.Rect(50, 50, 550, 800), stream=tiny_png_bytes())
    path = tmp_path / "scanned.pdf"
    doc.save(str(path))

    with pytest.raises(parsing.ParseError, match="扫描版"):
        parse_pdf(path, ctx)


def test_pdf_repeat_parse_is_identical(tmp_path, ctx) -> None:
    doc = _new_doc()
    page = doc.new_page()
    _line(page, 60, 80, "第一章 供给", 18)
    _line(page, 60, 110, "供给描述生产者的出售意愿。", 11)
    _line(page, 60, 170, "第二章 需求", 18)
    _line(page, 60, 200, "需求描述消费者的购买意愿。", 11)
    path = tmp_path / "stable.pdf"
    doc.save(str(path))

    assert parse_pdf(path, ctx).model_dump_json() == parse_pdf(path, ctx).model_dump_json()


def test_pdf_full_page_image_keeps_text(tmp_path, ctx) -> None:
    """整页底图（PPT 导出讲义形态）不得把该页正文连同图片一起剔除（M0 缺陷 #14 根因）。

    原始规则「图片块区域内的文本一律剔除」会把每页底图上的文字层全部删掉，
    8/10 页正文归零 → 章节因无段落被丢弃 → 目录指向不存在的章节。
    """
    import fitz

    doc = _new_doc()
    page = doc.new_page()
    page.insert_image(fitz.Rect(36, 30, 559, 812), stream=tiny_png_bytes())
    _line(page, 60, 80, "第一章 小市值策略导论", 18)
    _line(page, 60, 120, "若按「图片区内文本一律剔除」处理，本页正文会被整体抹掉。", 11)
    _line(page, 60, 150, "因此整页底图内的文本必须保留，否则章节会因无段落而被丢弃。", 11)
    path = tmp_path / "slide.pdf"
    doc.save(str(path))

    parsed = parse_pdf(path, ctx)
    joined = "".join(p.text for ch in parsed.chapters for p in ch.paras)
    assert "本页正文会被整体抹掉" in joined
    assert "否则章节会因无段落而被丢弃" in joined
    assert len(parsed.figures) >= 1  # 底图仍作为图表产物留档


def test_pdf_toc_has_no_dangling_chapter(tmp_path, ctx) -> None:
    """章节被丢弃时目录不得留下悬空条目：前端按 chapterId 查不到章会静默不跳转（M0 缺陷 #14）。"""
    import fitz

    doc = _new_doc()
    page = doc.new_page()
    _line(page, 60, 60, "第一章 供给", 18)
    _line(page, 60, 90, "供给描述生产者的出售意愿。", 11)
    _line(page, 60, 120, "价格上升时供给量增加。", 11)
    _line(page, 60, 150, "这是正文的正常段落。", 11)
    # 第二章整章落在插图区内 → 该章文本按图表兜底剔除 → 章节重组不出段落被丢弃
    page.insert_image(fitz.Rect(50, 200, 550, 600), stream=tiny_png_bytes())
    _line(page, 60, 240, "第二章 需求", 18)
    _line(page, 60, 280, "需求描述消费者的购买意愿。", 11)
    doc.set_toc([[1, "第一章 供给", 1], [1, "第二章 需求", 1]])
    path = tmp_path / "dangling.pdf"
    doc.save(str(path))

    parsed = parse_pdf(path, ctx)
    chapter_ids = {c.id for c in parsed.chapters}
    assert [t.title for t in parsed.toc] == ["第一章 供给"]
    assert all(t.chapterId in chapter_ids for t in parsed.toc)
    assert all(f.chapterId in chapter_ids for f in parsed.figures)  # 图表归属同样不得悬空
