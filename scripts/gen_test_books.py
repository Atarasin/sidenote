"""生成 5 本合成测试书（3 EPUB + 2 文字版 PDF），用于 M0 验收（计划 T0.5.1）。

真实经济学书的人工实测清单另见 docs/2026-09-02_M0解析缺陷清单.md；
本脚本产出覆盖以下特性组合：
  1. 经济学原理.epub      8 章、两级目录、表格、插图、引用块
  2. 货币银行学.epub      4 章、小节锚点目录
  3. 价格理论讲义.epub    2 章、极简结构（无图片无表格）
  4. 宏观经济分析.pdf     6 页单栏、字号章节切分、含插图页
  5. 计量经济学导论.pdf   4 页双栏、内置书签目录
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "server"))

OUT_DEFAULT = Path(__file__).resolve().parents[1] / "data" / "testbooks"


def tiny_png() -> bytes:
    import fitz

    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 240, 160))
    pix.set_rect(pix.irect, (59, 130, 246))
    return pix.tobytes("png")


def paras(prefix: str, n: int, start: int = 1) -> list[str]:
    """生成 n 段可读的经济学正文（每段独立成句，便于段落重组校验）。"""
    templates = [
        "{prefix}研究市场中价格与数量的决定机制，第{k}个要点是均衡的形成过程。",
        "{prefix}当外部冲击出现时，{prefix}框架预测供给或需求曲线将发生移动，第{k}类冲击来自技术变化。",
        "{prefix}的经验证据表明，第{k}次观察中价格调整的速度快于数量调整。",
        "{prefix}的政策含义是，第{k}种干预工具会改变激励结构而非直接改变结果。",
        "{prefix}在长期与短期表现不同，第{k}期的弹性估计值显著高于初期。",
    ]
    out = []
    for i in range(n):
        out.append(templates[i % len(templates)].format(prefix=prefix, k=start + i))
    return out


# ---------- EPUB ----------


def make_epub(path: Path, title: str, chapters: list[dict], toc, with_image=False) -> None:
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_identifier(f"test-{path.stem}")
    book.set_title(title)
    book.set_language("zh")
    book.add_author("合成测试作者")

    items = []
    for spec in chapters:
        item = epub.EpubHtml(title=spec["title"], file_name=spec["file"], lang="zh")
        item.content = spec["html"]
        book.add_item(item)
        items.append(item)

    if with_image:
        book.add_item(
            epub.EpubItem(file_name="images/curve.png", media_type="image/png", content=tiny_png())
        )

    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", *items]
    book.toc = toc if toc is not None else items
    epub.write_epub(str(path), book)


def epub_html(title: str, body_paras: list[str], extra: str = "") -> str:
    plist = "".join(f"<p>{p}</p>" for p in body_paras)
    return (
        "<html xmlns=\"http://www.w3.org/1999/xhtml\"><head>"
        f"<title>{title}</title></head><body><h1>{title}</h1>{plist}{extra}</body></html>"
    )


def gen_book1(out: Path) -> None:
    """经济学原理：8 章、两级目录、表格、插图。"""
    from ebooklib import epub

    chapters = []
    titles = [
        "第一章 稀缺与选择",
        "第二章 供给与需求",
        "第三章 弹性及其应用",
        "第四章 供需弹性与政策",
        "第五章 消费者选择",
        "第六章 生产成本",
        "第七章 完全竞争市场",
        "第八章 市场效率与失灵",
    ]
    for i, t in enumerate(titles, 1):
        extra = ""
        if i == 2:
            extra = (
                "<figure><img src='images/curve.png' alt='供需均衡曲线'/>"
                "<figcaption>图 2-1 供需均衡</figcaption></figure>"
                "<table><tr><th>年份</th><th>均衡价</th><th>均衡量</th></tr>"
                "<tr><td>2023</td><td>25 元</td><td>1200</td></tr>"
                "<tr><td>2024</td><td>30 元</td><td>1150</td></tr></table>"
            )
        if i == 3:
            extra = "<blockquote>弹性不是斜率，而是相对变化率之比。</blockquote>"
        chapters.append(
            {
                "file": f"ch{i}.xhtml",
                "title": t,
                "html": epub_html(t, paras("本章", 6), extra),
            }
        )
    toc = tuple(
        (
            epub.Section(t, href=f"ch{i}.xhtml"),
            (epub.Link(f"ch{i}.xhtml", "本章小结", f"sec{i}"),),
        )
        for i, t in enumerate(titles, 1)
    )
    make_epub(out / "经济学原理.epub", "经济学原理（合成测试）", chapters, toc, with_image=True)


def gen_book2(out: Path) -> None:
    """货币银行学：4 章、小节锚点。"""
    from ebooklib import epub

    titles = ["第一章 货币的本质", "第二章 商业银行体系", "第三章 中央银行", "第四章 货币政策"]
    chapters = []
    for i, t in enumerate(titles, 1):
        chapters.append(
            {"file": f"m{i}.xhtml", "title": t, "html": epub_html(t, paras("货币分析", 5))}
        )
    # 第二章带锚点小节
    chapters[1]["html"] = epub_html(
        titles[1],
        paras("货币分析", 3),
        "<h2 id='sec-credit'>信用创造机制</h2>" + "".join(
            f"<p>{p}</p>" for p in paras("信用创造", 2)
        ),
    )
    toc = (
        epub.Link("m1.xhtml", titles[0], "m1"),
        (
            epub.Section(titles[1], href="m2.xhtml"),
            (epub.Link("m2.xhtml#sec-credit", "信用创造机制", "sec-credit"),),
        ),
        epub.Link("m3.xhtml", titles[2], "m3"),
        epub.Link("m4.xhtml", titles[3], "m4"),
    )
    make_epub(out / "货币银行学.epub", "货币银行学（合成测试）", chapters, toc)


def gen_book3(out: Path) -> None:
    """价格理论讲义：2 章极简。"""
    titles = ["第一讲 价格的功能", "第二讲 价格管制"]
    chapters = [
        {"file": f"p{i}.xhtml", "title": t, "html": epub_html(t, paras("价格理论", 4))}
        for i, t in enumerate(titles, 1)
    ]
    make_epub(out / "价格理论讲义.epub", "价格理论讲义（合成测试）", chapters, None)


# ---------- PDF ----------


def _line(page, x, y, text, size=11.0):
    page.insert_text((x, y), text, fontname="china-s", fontsize=size)


def gen_book4(out: Path) -> None:
    """宏观经济分析：6 页单栏、字号章节切分、插图页。"""
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    _line(page, 200, 300, "宏观经济分析（合成测试）", 24)
    _line(page, 200, 340, "合成测试用书 · 单栏版", 12)
    for ch in range(1, 4):
        page = doc.new_page()
        _line(page, 60, 80, f"第三章之{ch} 增长与波动{'' if ch == 1 else '（续）'}", 17)
        y = 115
        for i, p in enumerate(paras("宏观分析", 8)):
            _line(page, 60, y, p, 11)
            y += 60
        if ch == 2:
            page.insert_image(fitz.Rect(200, 500, 400, 650), stream=tiny_png())
    doc.set_metadata({"title": "宏观经济分析（合成测试）", "author": "合成测试作者"})
    doc.save(str(out / "宏观经济分析.pdf"))
    doc.close()


def gen_book5(out: Path) -> None:
    """计量经济学导论：4 页双栏、内置书签。"""
    import fitz

    doc = fitz.open()
    toc_titles = ["第一章 经典线性回归", "第二章 假设检验", "第三章 异方差"]
    left_snippets = [
        "回归系数的OLS估计量。",
        "解释变量与误差项正交。",
        "样本容量决定方差。",
        "拟合优度不是全部。",
        "残差应服从正态分布。",
        "多重共线性放大方差。",
        "工具变量缓解内生性。",
        "大样本下推断渐近有效。",
    ]
    right_snippets = [
        "原假设设定为系数为零。",
        "t 检验适用于单一约束。",
        "F 检验处理联合约束。",
        "p 值是拒绝的最小水平。",
        "置信区间反映不确定性。",
        "第一类错误无法消除。",
        "功效随样本量上升。",
        "稳健标准误抗异方差。",
    ]
    for pg in range(4):
        page = doc.new_page()
        chapter = min(pg // 2 + pg % 2 * 0, 2) if False else min(pg, 2)
        if pg in (0, 2):  # 每两页换章
            title = toc_titles[chapter]
            _line(page, 60, 70, title, 16)
        for row in range(12):
            left_text = f"L{pg}{row:02d} {left_snippets[row % len(left_snippets)]}"
            right_text = f"R{pg}{row:02d} {right_snippets[row % len(right_snippets)]}"
            _line(page, 50, 110 + row * 55, left_text, 10)
            _line(page, 310, 110 + row * 55, right_text, 10)
    doc.set_toc([[1, toc_titles[0], 1], [1, toc_titles[1], 2], [1, toc_titles[2], 3]])
    doc.set_metadata({"title": "计量经济学导论（合成测试）", "author": "合成测试作者"})
    doc.save(str(out / "计量经济学导论.pdf"))
    doc.close()


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT_DEFAULT
    out.mkdir(parents=True, exist_ok=True)
    gen_book1(out)
    gen_book2(out)
    gen_book3(out)
    gen_book4(out)
    gen_book5(out)
    for f in sorted(out.iterdir()):
        print(f"{f.name}  {f.stat().st_size} bytes")


if __name__ == "__main__":
    main()
