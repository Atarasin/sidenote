"""书籍解析分发层：格式检测 + 解析器注册表（epub / pdf）。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

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

# 格式 → 解析器。懒加载填充（epub / pdf），避免模块级循环依赖。
PARSERS: dict[str, Parser] = {}


def _ensure_parsers_loaded() -> dict[str, Parser]:
    if not PARSERS:
        from . import epub_parser, pdf_parser

        PARSERS.update({"epub": epub_parser.parse_epub, "pdf": pdf_parser.parse_pdf})
    return PARSERS


def detect_format(file_name: str, head: bytes) -> str:
    """按扩展名 + 文件头判定格式；无法识别时抛 ParseError。"""
    lower = file_name.lower()
    if lower.endswith(".epub") or head.startswith(b"PK\x03\x04"):
        if not lower.endswith(".epub") and not head.startswith(b"PK"):
            raise ParseError("无法识别的文件格式（仅支持 EPUB / 文字版 PDF）")
        return "epub"
    if lower.endswith(".pdf") or head.startswith(b"%PDF"):
        return "pdf"
    raise ParseError("无法识别的文件格式（仅支持 EPUB / 文字版 PDF）")


def parse_book_file(path: Path, fmt: str, ctx: ParseContext) -> BookDoc:
    parser = _ensure_parsers_loaded().get(fmt)
    if parser is None:
        raise ParseError(f"{fmt} 解析器尚未注册")
    return parser(path, ctx)
