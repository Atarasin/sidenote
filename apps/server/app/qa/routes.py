"""问答 API（计划 T1.5.1 / T1.5.4，对前端开放——M3 便签卡与对话抽屉调用）。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..llm import router as llm_router
from .service import Citation, answer_question

router = APIRouter()


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    chapterId: str | None = None
    sessionId: str = ""


class CitationOut(BaseModel):
    paraId: str
    quote: str


class AskResultOut(BaseModel):
    answer: str
    citations: list[CitationOut] = Field(default_factory=list)
    hasBasis: bool = False
    witnessUsed: bool = False
    chapterId: str | None = None
    provider: str = ""
    retried: bool = False


@router.post("/{book_id}/ask")
async def ask(book_id: str, payload: AskRequest, request: Request) -> AskResultOut:
    storage = request.app.state.storage
    if storage.read_meta(book_id) is None:
        raise HTTPException(status_code=404, detail="书籍不存在")
    if storage.read_bookdoc(book_id) is None:
        raise HTTPException(status_code=409, detail="书籍尚未解析完成")

    backend = llm_router.get_backend(
        "long_text_qa", request.app.state.usage_log, mock_client=request.app.state.mock_llm
    )
    try:
        result: Citation | None = None  # 类型仅为可读性；真实结果是 AskResult
        result = await answer_question(
            storage,
            request.app.state.usage_log,
            backend,
            book_id,
            payload.question,
            payload.chapterId,
            session_id=payload.sessionId,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return AskResultOut(
        answer=result.answer,
        citations=[CitationOut(paraId=c.paraId, quote=c.quote) for c in result.citations],
        hasBasis=result.hasBasis,
        witnessUsed=result.witnessUsed,
        chapterId=result.chapterId,
        provider=result.provider,
        retried=result.retried,
    )
