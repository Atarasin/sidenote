"""图解产物模型与缓存（计划 Slice 2.4：同键只生成一次）。"""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field

from ..qa.service import Citation


class DiagramResult(BaseModel):
    cacheKey: str
    bookId: str
    paraId: str
    concept: str
    normalized: str
    kind: Literal["interactive", "incomplete", "degraded"] = "interactive"
    componentHtml: str = ""
    staticImage: str = ""  # 降级静态图 URL（相对 /api/books/{id}/diagrams-files/）
    explanation: str = ""  # 降级时的文字讲解 / 交互版的折叠讲解
    summary: str = ""
    citations: list[Citation] = Field(default_factory=list)
    cached: bool = False
    attempts: int = 0
    provider: str = ""


def make_cache_key(book_id: str, para_id: str, normalized_concept: str) -> str:
    raw = f"{book_id}:{para_id}:{normalized_concept}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]


def cache_path(storage, book_id: str, cache_key: str):
    return storage.diagrams_dir(book_id) / f"{cache_key}.json"


def load_cached(storage, book_id: str, cache_key: str) -> DiagramResult | None:
    path = cache_path(storage, book_id, cache_key)
    if not path.exists():
        return None
    try:
        return DiagramResult.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, ValueError):
        return None


def save_cached(storage, result: DiagramResult) -> None:
    path = cache_path(storage, result.bookId, result.cacheKey)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(path)  # 原子替换，避免并发写坏
