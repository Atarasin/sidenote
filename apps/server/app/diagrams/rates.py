"""会话生成频率限制（计划 T2.5.2 / 上游红线 3）。

计数、阈值、超限拒绝并返回明确状态（供前端「不允许静默失败」文案）。
持久化在 sessions/rate_limit.json；窗口按小时滚动。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

DEFAULT_LIMIT_PER_WINDOW = 20
DEFAULT_WINDOW_SECONDS = 3600


@dataclass
class RateState:
    limited: bool
    used: int
    limit: int
    window_seconds: int
    reset_at: float  # epoch 秒


class RateLimiter:
    def __init__(
        self,
        storage,
        limit: int = DEFAULT_LIMIT_PER_WINDOW,
        window_seconds: int = DEFAULT_WINDOW_SECONDS,
    ) -> None:
        self._storage = storage
        self._limit = limit
        self._window = window_seconds

    def _path(self):
        return self._storage.root / "sessions" / "rate_limit.json"

    def _load(self) -> dict:
        path = self._path()
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _save(self, data: dict) -> None:
        path = self._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    def check(self, session_id: str) -> RateState:
        data = self._load()
        entry = data.get(session_id) or {}
        now = time.time()
        start = float(entry.get("windowStart", 0))
        count = int(entry.get("count", 0))
        if now - start > self._window:
            start, count = now, 0
        return RateState(
            limited=count >= self._limit,
            used=count,
            limit=self._limit,
            window_seconds=self._window,
            reset_at=start + self._window,
        )

    def consume(self, session_id: str) -> RateState:
        """占一次生成名额；已超限则拒绝（状态不变）。"""
        state = self.check(session_id)
        if state.limited:
            return state
        data = self._load()
        entry = data.get(session_id) or {}
        now = time.time()
        start = float(entry.get("windowStart", 0))
        count = int(entry.get("count", 0))
        if now - start > self._window:
            start, count = now, 0
        data[session_id] = {"windowStart": start, "count": count + 1}
        self._save(data)
        return RateState(
            limited=False,
            used=count + 1,
            limit=self._limit,
            window_seconds=self._window,
            reset_at=start + self._window,
        )
