"""调用日志与计费统计（计划 T1.1.3）：usage/calls.jsonl 追加写。

成本闸门（M2 Slice 2.5）与费用呈现（M3 U6）都消费这里的数据源。
费用按 provider 价格表估算（人民币；未配置价格记 0 并标注 priced=false）。
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .types import Role, UsageInfo

_PRICE_KEYS = {
    "input_per_m": "prompt_tokens",
    "output_per_m": "completion_tokens",
    "cache_hit_per_m": "cache_hit_tokens",
}


class UsageLog:
    def __init__(self, storage) -> None:
        self._storage = storage
        self._lock = threading.Lock()
        self._prices: dict[str, dict[str, float]] = {}

    def register_price(self, provider: str, price: dict[str, Any]) -> None:
        self._prices[provider] = {k: float(price.get(k, 0) or 0) for k in _PRICE_KEYS}

    def estimate_cost_cny(self, provider: str, usage: UsageInfo) -> float:
        price = self._prices.get(provider, {})
        # 缓存命中是 prompt 的一部分：未命中部分按 input 价、命中部分按缓存价（重复前缀只计费一次）
        hit = min(usage.cache_hit_tokens, usage.prompt_tokens)
        miss = usage.prompt_tokens - hit
        cost = (
            miss * price.get("input_per_m", 0.0)
            + hit * price.get("cache_hit_per_m", 0.0)
            + usage.completion_tokens * price.get("output_per_m", 0.0)
        ) / 1_000_000
        return round(cost, 6)

    def record(
        self,
        *,
        role: Role | str,
        provider: str,
        model: str,
        usage: UsageInfo,
        duration_ms: int,
        status: str,
        book_id: str | None = None,
        purpose: str = "",
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        entry = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "role": str(role),
            "provider": provider,
            "model": model,
            "promptTokens": usage.prompt_tokens,
            "completionTokens": usage.completion_tokens,
            "cacheHitTokens": usage.cache_hit_tokens,
            "costCny": self.estimate_cost_cny(provider, usage),
            "priced": provider in self._prices,
            "durationMs": duration_ms,
            "status": status,
            "bookId": book_id,
            "purpose": purpose,
        }
        if extra:
            entry.update(extra)
        path = self._storage.usage_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def read_all(self) -> list[dict[str, Any]]:
        path: Path = self._storage.usage_log_path()
        if not path.exists():
            return []
        out = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
        return out

    def summary(self, *, book_id: str | None = None) -> dict[str, Any]:
        """会话累计统计（费用/次数/缓存命中/失败数）——M2 费用接口与 M3 呈现的数据源。"""
        calls = [
            c for c in self.read_all() if book_id is None or c.get("bookId") == book_id
        ]
        ok = [c for c in calls if c.get("status") == "ok"]
        return {
            "totalCalls": len(calls),
            "okCalls": len(ok),
            "failedCalls": len(calls) - len(ok),
            "totalCostCny": round(sum(c.get("costCny", 0) for c in calls), 6),
            "promptTokens": sum(c.get("promptTokens", 0) for c in calls),
            "completionTokens": sum(c.get("completionTokens", 0) for c in calls),
            "cacheHitTokens": sum(c.get("cacheHitTokens", 0) for c in calls),
            "cacheHitRate": (
                round(
                    sum(c.get("cacheHitTokens", 0) for c in calls)
                    / max(sum(c.get("promptTokens", 0) for c in calls), 1),
                    4,
                )
            ),
        }
