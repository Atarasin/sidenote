"""涂写意图解析服务（计划 T3.2.2 / T3.2.3）：合成图 + 附言 → paraId + 问题 + 链路。

- 真实路径：视觉模型（Kimi/GLM 视觉版）多模态消息（text + image_url）。
- mock 路径：按附言关键词在候选段落中确定性匹配（离线零外发，红线 1）。
- 产物校验：paraId 必须在候选内、route 只允许 qa/diagram；异常输出回退到
  「首个候选 + 附言即问题」——意图解析失败不阻断用户动线（转 QA 兜底）。
"""

from __future__ import annotations

import json
import re

from ..llm.types import ChatMessage
from .prompts import SCRIBBLE_INTENT_SYSTEM, intent_user_text

_ROUTES = {"qa", "diagram"}


def _parse_json(content: str) -> dict | None:
    text = content.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


async def parse_scribble_intent(
    backend,
    *,
    image: str,
    note: str,
    candidates: list[dict[str, str]],
    book_id: str,
    session_id: str = "local",
) -> dict:
    """返回 {paraId, question, route, concept}；candidates 形如 [{paraId, text}]。"""
    if not candidates:
        raise ValueError("候选段落为空：无法定位涂写指向")
    fallback = {
        "paraId": candidates[0]["paraId"],
        "question": note.strip() or "请讲解我圈选的这段内容",
        "route": "qa",
        "concept": "",
    }

    user_text = intent_user_text(note, candidates)
    # 视觉消息：文本段（附言+候选）+ 截图段；mock 应答器只消费文本段，接口与真实一致
    messages = [
        ChatMessage("system", SCRIBBLE_INTENT_SYSTEM),
        ChatMessage(
            "user",
            [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": image}},
            ],
        ),
    ]
    try:
        response = await backend.chat(
            "vision",
            messages,
            book_id=book_id,
            purpose="scribble_intent",
            session_id=session_id,
        )
    except Exception:
        return fallback  # 意图解析失败不阻断：回退 QA 兜底（调用方记录失败）

    data = _parse_json(response.content) or {}
    para_id = str(data.get("paraId", "")).strip()
    question = str(data.get("question", "")).strip()
    route = str(data.get("route", "qa")).strip()
    concept = str(data.get("concept", "")).strip()
    valid_ids = {c["paraId"] for c in candidates}
    if para_id not in valid_ids or not question or route not in _ROUTES:
        return fallback
    if route == "diagram" and not concept:
        concept = question[:24]
    return {"paraId": para_id, "question": question, "route": route, "concept": concept}
