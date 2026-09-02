"""FastAPI 入口：本地服务，只服务 sidenote 前端（CORS 仅放行 Vite dev server）。"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .books.routes import router as books_router
from .config import data_root
from .knowledge import mock_behaviors
from .knowledge.routes import router as knowledge_router
from .llm.mock import MockLLMClient
from .llm.usage import UsageLog
from .qa.routes import router as qa_router
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
    app.include_router(knowledge_router, prefix="/api/books")
    app.include_router(qa_router, prefix="/api/books")
    # 模型层共享实例：计费日志 + 无 key 时的离线 mock（按 purpose 分发生成行为）
    app.state.usage_log = UsageLog(app.state.storage)
    app.state.mock_llm = MockLLMClient(app.state.usage_log, responder=mock_behaviors.dispatch)

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "service": "sidenote"}

    return app


app = create_app()
