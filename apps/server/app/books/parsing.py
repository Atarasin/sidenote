"""书籍解析分发层：格式检测 + 解析器注册表（解析器实现在 Slice 0.2 落地）。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .models import BookDoc


class ParseError(Exception):
    """解析失败（格式不支持、文件损坏、无文字层等）。"""


@dataclass
class ParseContext:
    """解析器所需的外部信息与产物落点。"""

    book_id: str
    file_hash: str
    fallback_title: str  # 文件名主干；书内无题名时使用
    figures_dir: Path  # 图片产物落点（相对 imgPath 前缀为 figures/）


Parser = Callable[[Path, ParseContext], BookDoc]

# 格式 → 解析器。Slice 0.2 填充：epub / pdf。
PARSERS: dict[str, Parser] = {}


def detect_format(file_name: str, head: bytes) -> str:
    """按扩展名 + 文件头判定格式；无法识别时抛 ParseError。"""
    lower = file_name.lower()
    if lower.endswith(".epub") and head.startswith(b"PK"):
        return "epub"
    if lower.endswith(".pdf") or head.startswith(b"%PDF"):
        return "pdf"
    raise ParseError("无法识别的文件格式（仅支持 EPUB / 文字版 PDF）")


def parse_book_file(path: Path, fmt: str, ctx: ParseContext) -> BookDoc:
    parser = PARSERS.get(fmt)
    if parser is None:
        raise ParseError(f"{fmt} 解析器尚未注册")
    return parser(path, ctx)
