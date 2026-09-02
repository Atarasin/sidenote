"""文本清洗与乱码识别（图表兜底策略 T0.2.5 的辅助判定）。"""

from __future__ import annotations

import re
import unicodedata

_CID_RE = re.compile(r"\(cid:\d+\)")
_WS_RE = re.compile(r"\s+")
# 常见"可保留"字符：CJK、拉丁、数字、常用中英文标点、数学符号
_GOOD_RE = re.compile(
    r"[\u4e00-\u9fff\u3400-\u4dbf"  # CJK 统一表意
    r"A-Za-z0-9"
    r"，。、；：？！“”‘’（）《》〈〉【】—…·×÷±≥≤≈≠∞%‰"
    r"\.,;:?!\"'()\[\]{}<>/&\*+-=^_~$#@|\\"
    r" ]"
)


def normalize_text(raw: str) -> str:
    """压缩空白、去除零宽字符，保留正文。"""
    text = unicodedata.normalize("NFC", raw)
    text = text.replace("\u200b", "").replace("\ufeff", "").replace("\u00a0", " ")
    text = _WS_RE.sub(" ", text).strip()
    return text


def is_garbled(text: str) -> bool:
    """乱码/无意义文本判定：cid 占位符、替换符、可读字符占比过低。"""
    if not text:
        return True
    if _CID_RE.search(text):
        return True
    if "\ufffd" in text:
        return True
    good = len(_GOOD_RE.findall(text))
    return good / len(text) < 0.55


def is_chapter_heading_text(text: str) -> bool:
    """中文章节标题模式（PDF 无目录时的章节切分线索）。"""
    return bool(
        re.match(r"^第\s*[0-9一二三四五六七八九十百千两]+\s*[章部篇讲]", text)
        or re.match(r"^[0-9]{1,3}(\.[0-9]{1,2}){0,2}\s+\S", text)
        or re.match(r"^(Chapter|CHAPTER)\s+\d+", text)
    )
