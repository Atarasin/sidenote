"""涂写意图解析 API（计划 T3.2.2）：POST /api/books/{id}/scribbles/intent。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..llm import router as llm_router
from .service import parse_scribble_intent

router = APIRouter()

MAX_IMAGE_BYTES = 4 * 1024 * 1024  # 合成截图上限 4MB（dataURL 文本计）


class CandidateIn(BaseModel):
    paraId: str = Field(min_length=1, max_length=32)
    text: str = Field(max_length=2000)


class IntentRequest(BaseModel):
    image: str = Field(min_length=1, max_length=8 * 1024 * 1024)
    note: str = Field(default="", max_length=500)
    chapterId: str | None = None
    candidates: list[CandidateIn] = Field(min_length=1, max_length=12)
    sessionId: str = "local"


class IntentOut(BaseModel):
    paraId: str
    question: str
    route: str
    concept: str


@router.post("/{book_id}/scribbles/intent")
async def scribble_intent(book_id: str, payload: IntentRequest, request: Request) -> IntentOut:
    storage = request.app.state.storage
    if storage.read_meta(book_id) is None:
        raise HTTPException(status_code=404, detail="书籍不存在")
    if len(payload.image.encode("utf-8", errors="ignore")) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="截图过大，请缩小圈选范围")
    doc = storage.read_bookdoc(book_id)
    if doc is None:
        raise HTTPException(status_code=409, detail="书籍尚未解析完成")

    known = {p.id for ch in doc.chapters for p in ch.paras}
    candidates = [c.model_dump() for c in payload.candidates if c.paraId in known]
    if not candidates:
        raise HTTPException(status_code=400, detail="候选段落均不存在于本书")

    backend = llm_router.get_backend(
        "vision", request.app.state.usage_log, mock_client=request.app.state.mock_llm
    )
    try:
        result = await parse_scribble_intent(
            backend,
            image=payload.image,
            note=payload.note,
            candidates=candidates,
            book_id=book_id,
            session_id=payload.sessionId,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return IntentOut(**result)
