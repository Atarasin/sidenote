"""FastAPI 入口：本地服务，只服务 sidenote 前端（CORS 仅放行 Vite dev server）。"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .books.routes import router as books_router
from .config import data_root
from .storage import Storage

VITE_DEV_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


def create_app(storage: Storage | None = None) -> FastAPI:
    app = FastAPI(title="sidenote server", version="0.1.0")
    app.state.storage = storage if storage is not None else Storage(data_root())
    app.add_middleware(
        CORSMiddleware,
        allow_origins=VITE_DEV_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(books_router, prefix="/api/books")

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "service": "sidenote"}

    return app


app = create_app()
