"""全书理解接口：构建（后台）与查询。"""

from __future__ import annotations

import contextlib

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from ..llm import router as llm_router
from .models import load_knowledge

router = APIRouter()


def _backend_for(request: Request):
    return llm_router.get_backend(
        "long_text_qa", request.app.state.usage_log, mock_client=request.app.state.mock_llm
    )


async def _build_task(storage, book_id: str, backend) -> None:
    from .builder import build_book_knowledge

    with contextlib.suppress(Exception):
        await build_book_knowledge(storage, book_id, backend)


@router.post("/{book_id}/knowledge", status_code=202)
def build_knowledge(
    book_id: str,
    request: Request,
    background: BackgroundTasks,
    retry_failed: bool = False,
):
    storage = request.app.state.storage
    if storage.read_meta(book_id) is None:
        raise HTTPException(status_code=404, detail="书籍不存在")
    if storage.read_bookdoc(book_id) is None:
        raise HTTPException(status_code=409, detail="书籍尚未解析完成")
    background.add_task(_build_task, storage, book_id, _backend_for(request))
    return {"status": "building"}


@router.get("/{book_id}/knowledge")
def get_knowledge(book_id: str, request: Request):
    storage = request.app.state.storage
    knowledge = load_knowledge(storage, book_id)
    if knowledge is None:
        if storage.read_meta(book_id) is None:
            raise HTTPException(status_code=404, detail="书籍不存在")
        raise HTTPException(status_code=409, detail="全书理解尚未构建")
    return knowledge
