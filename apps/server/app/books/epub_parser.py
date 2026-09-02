"""EPUB 解析器（计划 T0.2.3）：目录树、章节切分、段落抽取、内嵌图片提取。

依赖 ebooklib + BeautifulSoup。同一文件重复解析结果一致（T0.2.2）：
章节按 spine 顺序编号、段落按文档顺序编号，均为确定性遍历。
"""

from __future__ import annotations

import posixpath
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup

from .models import (
    BookDoc,
    Chapter,
    DocMeta,
    Figure,
    Para,
    TocItem,
    make_chapter_id,
    make_para_id,
)
from .parsing import ParseContext, ParseError
from .text_utils import normalize_text

# 参与段落抽取的块级元素（文档序遍历，含祖先去重）
_BLOCK_TAGS = ("p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "pre", "table")
_IMG_TAGS = ("img", "image")

_IMG_EXT_BY_MEDIA = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/svg+xml": ".svg",
    "image/webp": ".webp",
}


def parse_epub(path, ctx: ParseContext) -> BookDoc:
    from ebooklib import epub

    try:
        book = epub.read_epub(str(path), options={"ignore_ncx": True})
    except Exception as exc:
        raise ParseError(f"EPUB 文件无法解析（可能已损坏）：{exc}") from exc

    meta = _build_meta(book, ctx)
    chapters, href_index, anchor_index, figures = _extract_chapters(book, ctx)
    if not chapters:
        raise ParseError("EPUB 中未抽取到任何正文段落")
    toc = _build_toc(book, href_index, anchor_index)
    return BookDoc(meta=meta, toc=toc, chapters=chapters, figures=figures)


def _build_meta(book, ctx: ParseContext) -> DocMeta:
    title = ""
    try:
        entries = book.get_metadata("DC", "title")
        if entries:
            title = str(entries[0][0] or "").strip()
    except Exception:
        title = ""
    authors: list[str] = []
    try:
        for value, _attrs in book.get_metadata("DC", "creator"):
            value = str(value).strip()
            if value:
                authors.append(value)
    except Exception:
        authors = []
    return DocMeta(
        bookId=ctx.book_id,
        title=title or ctx.fallback_title,
        authors=authors,
        format="epub",
        fileHash=ctx.file_hash,
    )


def _is_nav_document(item, soup) -> bool:
    """导航文档识别：EPUB3 属性标记（ebooklib 读回时常丢失，需内容特征兜底）。"""
    props = item.properties or []
    if isinstance(props, str):
        props = props.split()
    if "nav" in props:
        return True
    for nav in soup.find_all("nav"):
        epub_type = nav.get("epub:type") or nav.get("type")
        if epub_type and "toc" in str(epub_type):
            return True
    return False


def _spine_documents(book):
    """spine 顺序的内容文档（跳过 nav / 非正文 item）。"""
    import ebooklib

    docs = []
    for item in book.spine:
        itemref = item[0] if isinstance(item, (tuple, list)) else item
        if isinstance(itemref, str):
            itemref = book.get_item_with_id(itemref)
        if itemref is None or itemref.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        docs.append(itemref)
    return docs


def _extract_chapters(book, ctx: ParseContext):
    chapters: list[Chapter] = []
    figures: list[Figure] = []
    # href（含路径）→ 章序；anchor id → paraId
    href_index: dict[str, int] = {}
    anchor_index: dict[str, str] = {}

    for item in _spine_documents(book):
        try:
            raw = item.get_content()
        except Exception as exc:
            raise ParseError(f"EPUB 章节内容读取失败（{item.get_name()}）：{exc}") from exc
        soup = BeautifulSoup(raw, "lxml")
        if _is_nav_document(item, soup):
            continue
        body = soup.body or soup

        ch_idx = len(chapters) + 1
        chapter_id = make_chapter_id(ch_idx)
        paras: list[Para] = []
        chapter_figures: list[Figure] = []

        for el in body.find_all(_BLOCK_TAGS):
            # 祖先同为块级 → 交给祖先统一抽取，避免重复计数
            if el.find_parent(_BLOCK_TAGS) is not None:
                continue
            if el.name == "table":
                text = _table_to_text(el)
            else:
                text = normalize_text(el.get_text(" ", strip=True))
            if not text:
                continue
            para_idx = len(paras) + 1
            para = Para(id=make_para_id(ch_idx, para_idx), text=text)
            paras.append(para)
            for key in filter(None, (el.get("id"), el.get("name"))):
                anchor_index[f"{chapter_id}#{key}"] = para.id

        chapter_figures = _extract_images(book, body, item, chapter_id, ctx)

        if paras or chapter_figures:
            title = _first_heading_text(body) or _stem(item.get_name() or "")
            chapters.append(Chapter(id=chapter_id, title=title, paras=paras))
            figures.extend(chapter_figures)
            for variant in _href_variants(item.get_name() or ""):
                href_index[variant] = ch_idx

    return chapters, href_index, anchor_index, figures


def _table_to_text(table) -> str:
    """统计表格退化为单段文本：行内「，」连接、行间「；」连接。

    乱码文本由 is_garbled 在段落层面把关，不进上下文。
    """
    rows: list[str] = []
    for tr in table.find_all("tr"):
        cells = [normalize_text(td.get_text(" ", strip=True)) for td in tr.find_all(["td", "th"])]
        cells = [c for c in cells if c]
        if cells:
            rows.append("，".join(cells))
    return "；".join(rows)


def _first_heading_text(body) -> str:
    for tag in ("h1", "h2", "h3"):
        el = body.find(tag)
        if el is not None:
            text = normalize_text(el.get_text(" ", strip=True))
            if text:
                return text
    return ""


def _stem(name: str) -> str:
    base = posixpath.basename(name)
    return posixpath.splitext(base)[0] or "未命名章节"


def _href_variants(name: str) -> list[str]:
    name = unquote(name)
    base = posixpath.basename(name)
    variants = {name, base, f"OEBPS/{name}", f"Content/{name}", f"OPS/{name}"}
    return sorted(v for v in variants if v)


def _extract_images(book, body, item, chapter_id: str, ctx: ParseContext) -> list[Figure]:
    import ebooklib

    figures: list[Figure] = []
    seq = 0
    for el in body.find_all(_IMG_TAGS):
        ref = el.get("src") or el.get("xlink:href") or el.get("href") or ""
        if not ref:
            continue
        img_item = _resolve_image_item(book, item, ref)
        if img_item is None or img_item.get_type() != ebooklib.ITEM_IMAGE:
            continue
        seq += 1
        ext = _IMG_EXT_BY_MEDIA.get(
            img_item.media_type or "", posixpath.splitext(img_item.get_name() or "")[1] or ".png"
        )
        fig_name = f"fig-{chapter_id}-{seq:02d}{ext}"
        try:
            ctx.figures_dir.mkdir(parents=True, exist_ok=True)
            (ctx.figures_dir / fig_name).write_bytes(img_item.get_content())
        except Exception:
            seq -= 1
            continue
        caption = _image_caption(el)
        figures.append(
            Figure(
                id=fig_name.split(".")[0],
                chapterId=chapter_id,
                imgPath=f"figures/{fig_name}",
                caption=caption,
            )
        )
    return figures


def _resolve_image_item(book, current_item, ref: str):
    ref_clean = unquote(urlsplit(ref).path)
    candidates = {ref_clean, posixpath.basename(ref_clean)}
    # 相对当前文档目录归一
    try:
        base_dir = posixpath.dirname(current_item.get_name() or "")
        resolved = posixpath.normpath(posixpath.join(base_dir, ref_clean))
        candidates.add(resolved)
        candidates.add(posixpath.basename(resolved))
    except Exception:
        pass
    for candidate in candidates:
        found = book.get_item_with_href(candidate)
        if found is not None:
            return found
    # 兜底：按文件名扫描全部图片 item
    for img in book.get_items():
        if img.get_name() and posixpath.basename(img.get_name()) in candidates:
            return img
    return None


def _image_caption(el) -> str:
    container = el.find_parent("figure")
    if container is not None:
        cap = container.find("figcaption")
        if cap is not None:
            text = normalize_text(cap.get_text(" ", strip=True))
            if text:
                return text
    return normalize_text(el.get("alt") or el.get("title") or "")


def _build_toc(book, href_index: dict[str, int], anchor_index: dict[str, str]) -> list[TocItem]:

    items: list[TocItem] = []

    def resolve(href: str) -> tuple[int | None, str | None]:
        fragment = ""
        if "#" in href:
            href, fragment = href.split("#", 1)
        base = posixpath.basename(unquote(urlsplit(href).path))
        ch = href_index.get(unquote(href)) or href_index.get(base)
        para = None
        if ch is not None and fragment:
            para = anchor_index.get(f"{make_chapter_id(ch)}#{unquote(fragment)}")
        return ch, para

    def walk(entries, counter: list[int]) -> list[TocItem]:
        children_out: list[TocItem] = []
        for entry in entries or []:
            if isinstance(entry, tuple | list) and len(entry) == 2 and hasattr(entry[0], "href"):
                section, kids = entry
                href, title = section.href, section.title or ""
            elif hasattr(entry, "href"):
                href, title = entry.href, entry.title or ""
                kids = []
            else:
                continue
            ch, para = resolve(href)
            if ch is None:
                continue  # 指向不存在章节的目录项（如外链）直接丢弃
            counter[0] += 1
            children_out.append(
                TocItem(
                    id=f"toc-{counter[0]:03d}",
                    title=normalize_text(title) or "未命名",
                    chapterId=make_chapter_id(ch),
                    paraId=para,
                    children=walk(kids, counter),
                )
            )
        return children_out

    items = walk(book.toc, [0])
    return items
