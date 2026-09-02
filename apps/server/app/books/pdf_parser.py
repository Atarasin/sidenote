"""文字版 PDF 解析器（计划 T0.2.4 / T0.2.5）。

- 文本层抽取：PyMuPDF（fitz）结构化文本（块/行/跨度，含坐标与字号）。
- 阅读顺序还原：双栏按「先左栏后右栏」排序；标题等跨栏行按位置前置。
- 段落重组：垂直间距、字号跳变、项目符号、标题行、页界共同判定分段。
- 章节切分：优先 PDF 内置书签（toc level-1），退化为字号/「第X章」模式识别，再退化为全文单章。
- 图表兜底（T0.2.5）：嵌入图片块与「矢量密集 + 文字稀疏」的图表区域按原区域截图进 figures，
  该区域内的散落文本（坐标轴数字等）不进入正文，避免乱码上下文。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import BookDoc, Chapter, DocMeta, Figure, Para, TocItem, make_chapter_id, make_para_id
from .parsing import ParseContext, ParseError
from .text_utils import is_chapter_heading_text, is_garbled, normalize_text

_BULLET_RE = re.compile(
    r"^[•·▪‣◦\-–—*]\s+|^[（(]\s*\d+\s*[)）]|^\d{1,2}\s*[.、．]|^[一二三四五六七八九十]+[、.．]"
)

_MIN_TEXT_CHARS_PER_PAGE = 10  # 每页平均低于此字数视为无文字层（扫描版）；总下限 20 字
_MIN_TEXT_CHARS_TOTAL = 20
_VECTOR_CHART_MIN_DRAWINGS = 15  # 矢量线条数下限（曲线图/坐标系特征）
_VECTOR_CHART_MAX_TEXT_CHARS = 600  # 图表页文字量上限


@dataclass
class _Line:
    page: int
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    size: float
    bold: bool = False

    @property
    def height(self) -> float:
        return max(self.y1 - self.y0, 1.0)


@dataclass
class _Boundary:
    title: str
    page: int  # 0 起
    y: float
    chapter_index: int = field(default=0)


def parse_pdf(path, ctx: ParseContext) -> BookDoc:
    import fitz

    try:
        doc = fitz.open(str(path))
    except Exception as exc:
        raise ParseError(f"PDF 文件无法打开：{exc}") from exc
    if doc.is_encrypted:
        raise ParseError("PDF 已加密，暂不支持")
    if doc.page_count == 0:
        raise ParseError("PDF 没有任何页面")

    with doc:
        page_lines = _collect_lines(doc)
        total_chars = sum(len(line.text) for lines in page_lines for line in lines)
        if total_chars < max(_MIN_TEXT_CHARS_TOTAL, doc.page_count * _MIN_TEXT_CHARS_PER_PAGE):
            raise ParseError(
                "未检测到文字层（疑似扫描版 PDF）。"
                "扫描版 OCR 属二期范围，本期请上传 EPUB 或文字版 PDF"
            )

        body_size = _body_size(page_lines)
        boundaries = _detect_chapters(doc, page_lines, body_size)
        # 图表兜底区域：(page, x0, y0, x1, y1, fig_id, caption)
        figure_zones = _extract_figures(doc, ctx)
        lines = _drop_figure_text(page_lines, figure_zones)
        chapters = _build_chapters(lines, boundaries, body_size, ctx)
        meta = _build_meta(doc, ctx)

    if not chapters or not any(ch.paras for ch in chapters):
        raise ParseError("未从 PDF 中重组出任何正文段落")
    figures = _figures_from_zones(figure_zones, boundaries)
    toc = [
        TocItem(id=f"toc-{i:03d}", title=b.title, chapterId=make_chapter_id(b.chapter_index))
        for i, b in enumerate(boundaries, 1)
    ]
    return BookDoc(meta=meta, toc=toc, chapters=chapters, figures=figures)


# ---------- 文本行收集与排序 ----------


def _collect_lines(doc) -> list[list[_Line]]:
    all_pages: list[list[_Line]] = []
    for pno in range(doc.page_count):
        page = doc[pno]
        d = page.get_text("dict")
        lines: list[_Line] = []
        for block in d.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                text = "".join(s.get("text", "") for s in spans)
                if not text.strip():
                    continue
                sizes = [s["size"] for s in spans if s.get("text", "").strip()]
                bold = any("Bold" in s.get("font", "") for s in spans)
                x0, y0, x1, y1 = line["bbox"]
                lines.append(
                    _Line(
                        page=pno,
                        x0=x0,
                        y0=y0,
                        x1=x1,
                        y1=y1,
                        text=text,
                        size=max(sizes) if sizes else 10.0,
                        bold=bold,
                    )
                )
        all_pages.append(_ordered_page_lines(page.rect.width, lines))
    return all_pages


def _ordered_page_lines(page_width: float, lines: list[_Line]) -> list[_Line]:
    """单页阅读顺序：双栏按栏序，否则按 y 优先。"""
    if len(lines) <= 3:
        return sorted(lines, key=lambda ln: (ln.y0, ln.x0))
    mid = page_width / 2
    left = [ln for ln in lines if ln.x1 <= mid + 8]
    right = [ln for ln in lines if ln.x0 >= mid - 8 and ln.x1 > mid + 8]
    crossing = [ln for ln in lines if ln not in left and ln not in right]
    two_column = (
        len(left) >= 4
        and len(right) >= 4
        and len(crossing) <= max(3, int(0.25 * (len(left) + len(right))))
    )
    if two_column:
        top = min(ln.y0 for ln in left + right)
        by_pos = lambda ln: (ln.y0, ln.x0)  # noqa: E731
        above = sorted([ln for ln in crossing if ln.y1 <= top + 5], key=by_pos)
        below = sorted([ln for ln in crossing if ln.y1 > top + 5], key=by_pos)
        return above + sorted(left, key=by_pos) + sorted(right, key=by_pos) + below
    return sorted(lines, key=lambda ln: (round(ln.y0 / 4), ln.x0))


def _body_size(page_lines: list[list[_Line]]) -> float:
    weights: dict[float, int] = {}
    for lines in page_lines:
        for line in lines:
            weights[line.size] = weights.get(line.size, 0) + len(line.text)
    if not weights:
        return 10.0
    return max(weights.items(), key=lambda kv: kv[1])[0]


# ---------- 章节切分 ----------


def _is_heading(line: _Line, body_size: float) -> bool:
    text = normalize_text(line.text)
    if not text or len(text) > 60:
        return False
    return line.size >= body_size * 1.22 or is_chapter_heading_text(text)


def _detect_chapters(doc, page_lines: list[list[_Line]], body_size: float) -> list[_Boundary]:
    toc = [t for t in doc.get_toc() if t[0] == 1]
    boundaries: list[_Boundary] = []
    if len(toc) >= 2:
        for title, page_1based in ((t[1], t[2]) for t in toc):
            page = max(0, page_1based - 1)
            y = _title_y_on_page(page_lines, page, title)
            boundaries.append(_Boundary(title=normalize_text(title) or "未命名", page=page, y=y))
    else:
        flat = [line for lines in page_lines for line in lines]
        candidates = [
            line
            for line in flat
            if is_chapter_heading_text(normalize_text(line.text))
            or line.size >= body_size * 1.45
        ]
        # 去除相邻过近的候选（小节标题误判防线）
        filtered: list[_Line] = []
        for candidate in candidates:
            near_prev = (
                filtered
                and candidate.page == filtered[-1].page
                and candidate.y0 - filtered[-1].y0 < 20
            )
            if near_prev:
                continue
            filtered.append(candidate)
        for line in filtered:
            boundaries.append(
                _Boundary(title=normalize_text(line.text), page=line.page, y=line.y0)
            )
    if not boundaries or boundaries[0].page > 0:
        # 首章之前的封面/版权页内容归入第 0 章（序章）
        boundaries.insert(0, _Boundary(title="开篇", page=0, y=-1.0))
    for idx, b in enumerate(boundaries, 1):
        b.chapter_index = idx
    # 越界修正（书签页码超出实际页数）
    max_page = doc.page_count - 1
    boundaries = [b for b in boundaries if b.page <= max_page]
    for idx, b in enumerate(boundaries, 1):
        b.chapter_index = idx
    return boundaries


def _title_y_on_page(page_lines: list[list[_Line]], page: int, title: str) -> float:
    want = normalize_text(title)
    for line in page_lines[page] if page < len(page_lines) else []:
        text = normalize_text(line.text)
        head_match = want.startswith(text[: min(len(text), len(want))])
        if text and (head_match or text.startswith(want[:8])):
            return line.y0
    return 0.0


def _chapter_of(boundaries: list[_Boundary], page: int, y: float) -> int:
    """定位 (page, y) 所属章节序。"""
    current = boundaries[0].chapter_index
    for b in boundaries:
        if (b.page, b.y) <= (page, y):
            current = b.chapter_index
        else:
            break
    return current


def _build_chapters(
    ordered_pages: list[list[_Line]],
    boundaries: list[_Boundary],
    body_size: float,
    ctx: ParseContext,
) -> list[Chapter]:
    by_chapter: dict[int, list[_Line]] = {}
    for lines in ordered_pages:
        for line in lines:
            ch = _chapter_of(boundaries, line.page, line.y0)
            by_chapter.setdefault(ch, []).append(line)

    chapters: list[Chapter] = []
    for ch_idx in sorted(by_chapter):
        paras_raw = _assemble_paras(by_chapter[ch_idx], body_size)
        if not paras_raw:
            continue
        title = next((b.title for b in boundaries if b.chapter_index == ch_idx), None)
        paras = [
            Para(id=make_para_id(ch_idx, i), text=text, page=page)
            for i, (text, page) in enumerate(paras_raw, 1)
        ]
        chapters.append(
            Chapter(id=make_chapter_id(ch_idx), title=title or f"第 {ch_idx} 节", paras=paras)
        )
    return chapters


# ---------- 段落重组 ----------


def _assemble_paras(lines: list[_Line], body_size: float) -> list[tuple[str, int]]:
    paras: list[tuple[str, int]] = []
    buf = ""
    buf_page: int | None = None
    prev: _Line | None = None

    def flush() -> None:
        nonlocal buf, buf_page
        text = normalize_text(buf)
        if text and not is_garbled(text):
            paras.append((text, buf_page if buf_page is not None else 0))
        buf, buf_page = "", None

    for line in lines:
        text = normalize_text(line.text)
        if not text:
            continue
        heading = _is_heading(line, body_size)
        if heading:
            flush()
            if not is_garbled(text):
                paras.append((text, line.page))
            prev = line
            continue
        new_para = prev is None or heading
        if prev is not None and not new_para:
            gap = line.y0 - prev.y1
            if line.page != prev.page:
                new_para = prev.text.rstrip()[-1:] in "。！？；…!?;"
            else:
                new_para = (
                    gap > 1.6 * prev.height
                    or _BULLET_RE.match(text) is not None
                    or abs(line.size - prev.size) > max(1.5, body_size * 0.15)
                )
        if new_para:
            flush()
            buf, buf_page = text, line.page
        else:
            joiner = "" if _cjk_join(buf[-1:], text[0]) else " "
            buf += joiner + text
        prev = line
    flush()
    return paras


def _cjk_join(left: str, right: str) -> bool:
    if not left or not right:
        return True

    def cjk(ch: str) -> bool:
        return "\u4e00" <= ch <= "\u9fff" or ch in "，。、；：？！“”‘’（）《》—…"

    return cjk(left[-1]) or cjk(right[0])


# ---------- 图表兜底（T0.2.5） ----------


def _extract_figures(doc, ctx: ParseContext) -> list[tuple]:
    """收集图表区域并截图落盘。返回 (page, x0, y0, x1, y1, fig_id, caption) 元组列表。"""
    import fitz

    zones: list[tuple] = []
    for pno in range(doc.page_count):
        page = doc[pno]
        d = page.get_text("dict")
        seq = 0

        # 1) 嵌入图片块
        for block in d.get("blocks", []):
            if block.get("type") != 1:
                continue
            rect = fitz.Rect(block["bbox"])
            if rect.width < 24 or rect.height < 24:
                continue
            seq += 1
            fig_id, caption = _render_zone(page, rect, pno, seq, ctx)
            if fig_id:
                zones.append((pno, rect.x0, rect.y0, rect.x1, rect.y1, fig_id, caption))

        # 2) 矢量密集 + 文字稀疏的图表区（曲线图/坐标系兜底）
        page_text_chars = sum(
            len(s.get("text", "")) for b in d.get("blocks", []) if b.get("type") == 0 for s in (
                span for line in b.get("lines", []) for span in line.get("spans", [])
            )
        )
        if page_text_chars >= _VECTOR_CHART_MAX_TEXT_CHARS:
            continue
        drawings = page.get_drawings()
        if len(drawings) < _VECTOR_CHART_MIN_DRAWINGS:
            continue
        rect = fitz.Rect()
        for dr in drawings:
            rect |= fitz.Rect(dr["rect"])
        if rect.is_empty or rect.get_area() < 0.15 * page.rect.get_area():
            continue
        seq += 1
        fig_id, caption = _render_zone(page, rect, pno, seq, ctx, vector=True)
        if fig_id:
            zones.append((pno, rect.x0, rect.y0, rect.x1, rect.y1, fig_id, caption))
    return zones


def _render_zone(page, rect, pno: int, seq: int, ctx: ParseContext, vector: bool = False):
    import fitz

    clip = fitz.Rect(rect) & page.rect
    if clip.is_empty or clip.width < 24 or clip.height < 24:
        return None, ""
    try:
        pix = page.get_pixmap(clip=clip, matrix=fitz.Matrix(2, 2), alpha=False)
        fig_id = f"fig-p{pno + 1:03d}-{seq:02d}"
        ctx.figures_dir.mkdir(parents=True, exist_ok=True)
        pix.save(str(ctx.figures_dir / f"{fig_id}.png"))
    except Exception:
        return None, ""
    caption = f"第 {pno + 1} 页图表（原区域截图）" if vector else f"第 {pno + 1} 页插图"
    return fig_id, caption


def _drop_figure_text(
    page_lines: list[list[_Line]], zones: list[tuple]
) -> list[list[_Line]]:
    """矢量图表区域内的散落文本（坐标轴标签等）不进入正文（不输出乱码文本进上下文）。"""
    zones_by_page: dict[int, list[tuple]] = {}
    for zone in zones:
        zones_by_page.setdefault(zone[0], []).append(zone)

    def in_zone(line: _Line) -> bool:
        for _page, x0, y0, x1, y1, _fid, _cap in zones_by_page.get(line.page, []):
            if line.x0 >= x0 - 2 and line.x1 <= x1 + 2 and line.y0 >= y0 - 2 and line.y1 <= y1 + 2:
                return True
        return False

    return [
        [line for line in lines if not in_zone(line)]
        for lines in page_lines
    ]


def _figures_from_zones(zones: list[tuple], boundaries: list[_Boundary]) -> list[Figure]:
    seen: set[str] = set()
    out: list[Figure] = []
    for page, _x0, y0, _x1, y1, fig_id, caption in zones:
        if fig_id in seen:
            continue
        seen.add(fig_id)
        ch = _chapter_of(boundaries, page, (y0 + y1) / 2)
        out.append(
            Figure(
                id=fig_id,
                chapterId=make_chapter_id(ch),
                imgPath=f"figures/{fig_id}.png",
                caption=caption,
            )
        )
    return out

# ---------- 元数据 ----------


def _build_meta(doc, ctx: ParseContext) -> DocMeta:
    info = doc.metadata or {}
    title = normalize_text(str(info.get("title") or ""))
    authors = [
        normalize_text(a)
        for a in str(info.get("author") or "").replace("，", ";").replace(",", ";").split(";")
        if normalize_text(a)
    ]
    return DocMeta(
        bookId=ctx.book_id,
        title=title or ctx.fallback_title,
        authors=authors,
        format="pdf",
        fileHash=ctx.file_hash,
    )
