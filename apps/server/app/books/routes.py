"""书籍上传与访问接口（计划 T0.1.3）。不做书库管理界面，只提供打开书所需的最低接口。"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from ..storage import Storage, utc_now_iso
from . import parsing
from .models import BookFileMeta

router = APIRouter()

ALLOWED_SUFFIXES = {".epub", ".pdf"}


def _get_storage(request: Request) -> Storage:
    storage: Storage = request.app.state.storage
    storage.ensure_layout()
    return storage


def _stem(file_name: str) -> str:
    return Path(file_name).stem or "未命名书籍"


async def _save_upload(storage: Storage, upload: UploadFile, file_name: str) -> Path:
    """流式落盘到 tmp/，返回临时文件路径。超限立即中断。"""
    from ..config import max_upload_bytes

    cap = max_upload_bytes()
    storage.tmp_dir().mkdir(parents=True, exist_ok=True)
    tmp_path = storage.tmp_dir() / f"{uuid.uuid4().hex}.upload"
    written = 0
    try:
        with tmp_path.open("wb") as out:
            while chunk := await upload.read(1024 * 1024):
                written += len(chunk)
                if written > cap:
                    detail = f"文件超过大小上限 {cap // 1024 // 1024}MB"
                    raise HTTPException(status_code=413, detail=detail)
                out.write(chunk)
        if written == 0:
            raise HTTPException(status_code=400, detail="上传文件为空")
    except HTTPException:
        tmp_path.unlink(missing_ok=True)
        raise
    return tmp_path


@router.post("", status_code=201)
async def upload_book(
    background: BackgroundTasks,
    request: Request,
    file: Annotated[UploadFile, File()],
) -> BookFileMeta:
    storage = _get_storage(request)
    file_name = file.filename or "book"
    if Path(file_name).suffix.lower() not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=400, detail="仅支持 EPUB / PDF 文件")

    tmp_path = await _save_upload(storage, file, file_name)
    try:
        with tmp_path.open("rb") as fh:
            head = fh.read(8)
        try:
            fmt = parsing.detect_format(file_name, head)
        except parsing.ParseError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        file_hash = Storage.sha256_file(tmp_path)
        book_id = Storage.book_id_for(file_hash)

        # 同文件哈希不重复解析（计划 T0.2.6 的入口侧去重）
        existing = storage.read_meta(book_id)
        if existing is not None and existing.parseStatus in ("success", "parsing"):
            return existing

        book_dir = storage.book_dir(book_id)
        book_dir.mkdir(parents=True, exist_ok=True)
        storage.figures_dir(book_id).mkdir(exist_ok=True)
        target = storage.source_path(book_id, fmt)
        tmp_path.replace(target)

        meta = BookFileMeta(
            bookId=book_id,
            title=_stem(file_name),
            format=fmt,
            fileHash=file_hash,
            fileName=file_name,
            sizeBytes=target.stat().st_size,
            addedAt=utc_now_iso(),
            parseStatus="pending",
        )
        storage.write_meta(meta)
    finally:
        tmp_path.unlink(missing_ok=True)

    background.add_task(run_parse, storage, book_id)
    return meta


def run_parse(storage: Storage, book_id: str) -> None:
    """后台解析：状态落盘，失败不抛出（记录到 meta.parseError）。

    T0.2.6 落盘缓存：已成功且产物在盘的书直接跳过，同文件哈希不重复解析。
    """
    meta = storage.read_meta(book_id)
    if meta is None:
        return
    if meta.parseStatus == "success" and storage.read_bookdoc(book_id) is not None:
        return
    source = storage.source_path(book_id, meta.format)
    if not source.exists():
        return
    meta.parseStatus = "parsing"
    meta.parseError = None
    storage.write_meta(meta)
    ctx = parsing.ParseContext(
        book_id=book_id,
        file_hash=meta.fileHash,
        fallback_title=meta.title,
        figures_dir=storage.figures_dir(book_id),
    )
    try:
        doc = parsing.parse_book_file(source, meta.format, ctx)
    except parsing.ParseError as exc:
        meta.parseStatus = "failed"
        meta.parseError = str(exc)
        storage.write_meta(meta)
        return
    except Exception as exc:
        meta.parseStatus = "failed"
        meta.parseError = f"解析器异常：{exc!r}"
        storage.write_meta(meta)
        return

    storage.write_bookdoc(doc)
    meta.title = doc.meta.title
    meta.parseStatus = "success"
    meta.parseError = None
    meta.chaptersCount = len(doc.chapters)
    meta.parasCount = sum(len(ch.paras) for ch in doc.chapters)
    storage.write_meta(meta)


@router.get("")
def list_books(request: Request) -> list[BookFileMeta]:
    return _get_storage(request).list_books()


@router.get("/{book_id}")
def get_book(book_id: str, request: Request) -> BookFileMeta:
    meta = _get_storage(request).read_meta(book_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="书籍不存在")
    return meta


@router.get("/{book_id}/bookdoc")
def get_bookdoc(book_id: str, request: Request):
    storage = _get_storage(request)
    doc = storage.read_bookdoc(book_id)
    if doc is None:
        meta = storage.read_meta(book_id)
        if meta is None:
            raise HTTPException(status_code=404, detail="书籍不存在")
        raise HTTPException(status_code=409, detail=f"书籍尚未解析完成（状态：{meta.parseStatus}）")
    return doc


_FIGURE_NAME_RE = re.compile(r"^[\w.\-]+$")


@router.get("/{book_id}/figures/{figure_file}")
def get_figure(book_id: str, figure_file: str, request: Request) -> FileResponse:
    storage = _get_storage(request)
    if not _FIGURE_NAME_RE.match(figure_file):
        raise HTTPException(status_code=400, detail="非法的图片文件名")
    path = storage.figures_dir(book_id) / figure_file
    if not path.is_file():
        raise HTTPException(status_code=404, detail="图片不存在")
    return FileResponse(path)
