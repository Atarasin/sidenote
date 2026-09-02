"""费用与限流数据接口（计划 T2.5.3，消费 T1.1.3 的调用日志）。"""

from __future__ import annotations

from fastapi import APIRouter, Request

from .config import load_config
from .diagrams.rates import DEFAULT_LIMIT_PER_WINDOW, DEFAULT_WINDOW_SECONDS, RateLimiter

router = APIRouter()


@router.get("/usage/summary")
def usage_summary(sessionId: str | None = None, bookId: str | None = None, request: Request = None):
    usage_log = request.app.state.usage_log
    storage = request.app.state.storage
    limits = load_config().get("generation_limits", {})
    limiter = RateLimiter(
        storage,
        limit=int(limits.get("per_session", DEFAULT_LIMIT_PER_WINDOW)),
        window_seconds=int(limits.get("window_seconds", DEFAULT_WINDOW_SECONDS)),
    )
    rate = limiter.check(sessionId or "local")
    summary = usage_log.summary(book_id=bookId, session_id=sessionId)
    return {
        **summary,
        "rateLimit": {
            "used": rate.used,
            "limit": rate.limit,
            "limited": rate.limited,
            "resetAt": rate.reset_at,
        },
    }
