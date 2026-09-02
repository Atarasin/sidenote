"""用 ebooklib 生成测试用 EPUB 夹具（含目录、章节、图片、锚点）。"""

from __future__ import annotations

from pathlib import Path


def tiny_png_bytes() -> bytes:
    import fitz

    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 32, 32))
    pix.set_rect(pix.irect, (200, 60, 60))
    return pix.tobytes("png")


def build_epub(
    path: Path,
    *,
    title: str = "经济学入门（测试书）",
    chapters: list[dict],
    toc=None,
    with_image: bool = False,
) -> Path:
    """chapters: [{file_name, title, html}]；toc 直接传 ebooklib toc 结构。"""
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_identifier("test-book-0001")
    book.set_title(title)
    book.set_language("zh")
    book.add_author("测试作者")

    chapter_items = []
    for spec in chapters:
        item = epub.EpubHtml(title=spec["title"], file_name=spec["file_name"], lang="zh")
        item.content = spec["html"]
        book.add_item(item)
        chapter_items.append(item)

    if with_image:
        img = epub.EpubItem(
            file_name="images/fig1.png", media_type="image/png", content=tiny_png_bytes()
        )
        book.add_item(img)

    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", *chapter_items]
    book.toc = toc if toc is not None else chapter_items
    epub.write_epub(str(path), book)
    return path
