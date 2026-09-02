"""图解 API（计划 T2.1.2 / T2.5.2 / T2.5.3）：生成、修复重试、降级、缓存与静态图文件。"""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from ..config import load_config
from ..llm import router as llm_router
from .models import DiagramResult, load_cached, make_cache_key
from .normalize import normalize_concept
from .rates import DEFAULT_LIMIT_PER_WINDOW, DEFAULT_WINDOW_SECONDS, RateLimiter
from .service import DiagramLimited, degrade_diagram, generate_diagram

router = APIRouter()

_FILE_RE = re.compile(r"^[\w.\-]+\.(png|svg|jpg|jpeg|webp)$")


def _limiter(storage) -> RateLimiter:
    limits = load_config().get("generation_limits", {})
    return RateLimiter(
        storage,
        limit=int(limits.get("per_session", DEFAULT_LIMIT_PER_WINDOW)),
        window_seconds=int(limits.get("window_seconds", DEFAULT_WINDOW_SECONDS)),
    )


class DiagramRequest(BaseModel):
    paraId: str
    concept: str = Field(min_length=1, max_length=120)
    sessionId: str = "local"
    repair: bool = False
    failReason: str = ""


class DegradeRequest(BaseModel):
    paraId: str
    concept: str = Field(min_length=1, max_length=120)
    sessionId: str = "local"


def _result_out(result: DiagramResult, rate_state) -> dict:
    data = result.model_dump()
    data["rateLimit"] = {
        "used": rate_state.used,
        "limit": rate_state.limit,
        "limited": rate_state.limited,
        "resetAt": rate_state.reset_at,
    }
    return data


def _backends(request: Request):
    qa_backend = llm_router.get_backend(
        "long_text_qa", request.app.state.usage_log, mock_client=request.app.state.mock_llm
    )
    t2i_backend = llm_router.get_backend(
        "text_to_image", request.app.state.usage_log, mock_client=request.app.state.mock_llm
    )
    return qa_backend, t2i_backend


@router.post("/{book_id}/diagrams")
async def create_diagram(book_id: str, payload: DiagramRequest, request: Request):
    storage = request.app.state.storage
    if storage.read_meta(book_id) is None:
        raise HTTPException(status_code=404, detail="书籍不存在")
    limiter = _limiter(storage)
    try:
        result = await generate_diagram(
            storage,
            _backends(request)[0],
            book_id,
            payload.paraId,
            payload.concept,
            limiter=limiter,
            session_id=payload.sessionId,
            repair=payload.repair,
            fail_reason=payload.failReason,
        )
    except DiagramLimited as exc:
        # 频率限制必须显式反馈（红线 3 / UI 红线 3：禁止静默失败）
        return JSONResponse(
            status_code=429,
            content={
                "detail": str(exc),
                "rateLimit": {
                    "used": exc.state.used,
                    "limit": exc.state.limit,
                    "limited": True,
                    "resetAt": exc.state.reset_at,
                },
            },
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _result_out(result, limiter.check(payload.sessionId))


@router.post("/{book_id}/diagrams/degrade")
async def degrade(book_id: str, payload: DegradeRequest, request: Request):
    storage = request.app.state.storage
    if storage.read_meta(book_id) is None:
        raise HTTPException(status_code=404, detail="书籍不存在")
    try:
        qa_backend, t2i_backend = _backends(request)
        result = await degrade_diagram(
            storage,
            qa_backend,
            t2i_backend,
            book_id,
            payload.paraId,
            payload.concept,
            session_id=payload.sessionId,
            usage_log=request.app.state.usage_log,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _result_out(result, _limiter(storage).check(payload.sessionId))


@router.get("/{book_id}/diagrams/{para_id}/{concept}")
def get_diagram(book_id: str, para_id: str, concept: str, request: Request):
    storage = request.app.state.storage
    normalized = normalize_concept(concept)
    result = load_cached(storage, book_id, make_cache_key(book_id, para_id, normalized))
    if result is None:
        raise HTTPException(status_code=404, detail="未生成过该概念的图解")
    result.cached = True
    return _result_out(result, _limiter(storage).check("local"))


@router.get("/{book_id}/diagrams-files/{file_name}")
def get_diagram_file(book_id: str, file_name: str, request: Request) -> FileResponse:
    storage = request.app.state.storage
    if storage.read_meta(book_id) is None:
        raise HTTPException(status_code=404, detail="书籍不存在")
    if not _FILE_RE.match(file_name):
        raise HTTPException(status_code=400, detail="非法的图解文件名")
    path = storage.diagrams_dir(book_id) / "files" / file_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="图解文件不存在")
    media = "image/svg+xml" if file_name.endswith(".svg") else "image/png"
    return FileResponse(path, media_type=media)
