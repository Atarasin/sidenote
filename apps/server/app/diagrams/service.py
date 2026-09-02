"""图解生成主链路（计划 Slice 2.1 / 2.2.3 / 2.3 / 2.4 / 2.5）。

- 缓存优先（T2.5.1 / T2.4.1）：书ID+段落ID+概念规范化名 命中直接返回，零生成调用。
- 频率限制（T2.5.2）：超限拒绝并返回明确状态。
- 生成 → 引用校验 → 缓存落盘；沙箱渲染失败由前端检测后调 repair=true 重试一次（T2.2.3）；
  重试仍失败由前端调 degrade 走静态图降级（T2.3.2），降级态写入缓存。
"""

from __future__ import annotations

import json
import re

from ..llm.errors import ModelError
from ..llm.types import ChatMessage
from ..qa.service import validate_citations
from .models import (
    DiagramResult,
    load_cached,
    make_cache_key,
    save_cached,
)
from .normalize import normalize_concept
from .prompts import DEGRADE_EXPLAIN_SYSTEM, diagram_messages
from .rates import RateLimiter, RateState


class DiagramLimited(Exception):
    """触发会话频率限制（T2.5.2）：携带明确状态供前端呈现，禁止静默失败。"""

    def __init__(self, state: RateState) -> None:
        super().__init__("已达本会话生成频率上限，请稍后再试")
        self.state = state


def _parse_component_json(content: str) -> dict | None:
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


async def generate_diagram(
    storage,
    backend,
    book_id: str,
    para_id: str,
    concept: str,
    *,
    limiter: RateLimiter,
    session_id: str = "local",
    repair: bool = False,
    fail_reason: str = "",
) -> DiagramResult:
    doc = storage.read_bookdoc(book_id)
    if doc is None:
        raise FileNotFoundError(f"书籍未解析：{book_id}")
    para = next((p for ch in doc.chapters for p in ch.paras if p.id == para_id), None)
    if para is None:
        raise ValueError(f"段落不存在：{para_id}")

    normalized = normalize_concept(concept)
    cache_key = make_cache_key(book_id, para_id, normalized)

    # 缓存优先（T2.4.1 同键只生成一次；修复重试不新建键）
    cached = load_cached(storage, book_id, cache_key)
    if cached and not repair:
        cached.cached = True
        return cached
    if cached and repair and cached.kind == "degraded":
        cached.cached = True  # 已降级态不再重试（避免重复烧费）
        return cached
    if cached and repair and cached.attempts >= 2:
        cached.cached = True
        return cached  # 主链路只允许 1 次修复重试（上游 D3/R2）

    # 频率限制：缓存未命中且需要新生成时占名额
    state = limiter.consume(session_id)
    if state.limited:
        raise DiagramLimited(state)

    result = cached or DiagramResult(
        cacheKey=cache_key,
        bookId=book_id,
        paraId=para_id,
        concept=concept,
        normalized=normalized,
    )
    result.attempts += 1
    result.provider = getattr(backend, "provider", "")

    try:
        response = await backend.chat(
            "long_text_qa",
            diagram_messages(
                normalized, para.text, para_id, repair=repair, fail_reason=fail_reason
            ),
            book_id=book_id,
            purpose="diagram_repair" if repair else "diagram",
            session_id=session_id,
        )
    except ModelError as exc:
        raise ModelError(exc.kind, f"图解生成失败：{exc}") from exc

    data = _parse_component_json(response.content)
    component = (data or {}).get("componentHtml") or ""
    citations = validate_citations(doc, (data or {}).get("citations") or [])
    summary = str((data or {}).get("summary", "")).strip()
    if component and citations:
        result.kind = "interactive"
        result.componentHtml = component
        result.summary = summary or "（见图解）"
        result.citations = citations
    else:
        # 生成产物不完整 → 视为一次失败尝试（前端可 repair 或 degrade）
        result.componentHtml = ""
        result.summary = summary
        result.citations = []
        result.kind = "interactive"
    save_cached(storage, result)
    return result


async def degrade_diagram(
    storage,
    backend,
    t2i_backend,
    book_id: str,
    para_id: str,
    concept: str,
) -> DiagramResult:
    """静态图降级（计划 T2.3.2）：重试仍失败 → 静态图 + 文字讲解；降级态写入缓存。"""
    doc = storage.read_bookdoc(book_id)
    if doc is None:
        raise FileNotFoundError(f"书籍未解析：{book_id}")
    para = next((p for ch in doc.chapters for p in ch.paras if p.id == para_id), None)
    if para is None:
        raise ValueError(f"段落不存在：{para_id}")

    normalized = normalize_concept(concept)
    cache_key = make_cache_key(book_id, para_id, normalized)
    result = load_cached(storage, book_id, cache_key) or DiagramResult(
        cacheKey=cache_key,
        bookId=book_id,
        paraId=para_id,
        concept=concept,
        normalized=normalized,
    )
    if result.kind == "degraded":
        result.cached = True
        return result  # 降级态已在缓存，避免重复烧费

    # 1) 文字讲解（长文模型）
    try:
        explain = await backend.chat(
            "long_text_qa",
            [
                ChatMessage("system", DEGRADE_EXPLAIN_SYSTEM),
                ChatMessage(
                    "user",
                    f"概念：{normalized}\n【段落内容】\n{para.text}\n【/段落内容】",
                ),
            ],
            book_id=book_id,
            purpose="diagram_explain",
        )
        explanation = explain.content.strip()[:400]
    except ModelError:
        explanation = para.text[:120]  # 讲解失败退化为原文摘录

    # 2) 静态图（文生图服务；mock 生成确定性 SVG）
    image_rel = await render_static_image(
        t2i_backend, storage, book_id, cache_key, normalized, para.text
    )

    result.kind = "degraded"
    result.componentHtml = ""
    result.staticImage = image_rel
    result.explanation = explanation
    result.summary = result.summary or "（静态图解）"
    result.provider = getattr(backend, "provider", "")
    save_cached(storage, result)
    return result


async def render_static_image(
    t2i_backend,
    storage,
    book_id: str,
    cache_key: str,
    concept: str,
    para_text: str,
) -> str:
    """文生图（T2.3.1）：真实服务（CogView）返回图片 URL/bytes；mock 生成确定性 SVG。"""
    provider = getattr(t2i_backend, "provider", "mock")
    if provider == "mock":
        # 离线确定性静态图：透明背景、currentColor 不可用于 <img>，改深浅双适配的中性色
        svg = f"""<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 480 270'>
  <rect width='480' height='270' fill='#f8fafc' rx='12'/>
  <g stroke='#334155' stroke-width='2' fill='none'>
    <line x1='60' y1='220' x2='420' y2='220'/>
    <line x1='60' y1='30' x2='60' y2='220'/>
    <line x1='90' y1='60' x2='380' y2='190' stroke='#0f766e'/>
    <line x1='90' y1='190' x2='380' y2='60' stroke='#b91c1c'/>
    <circle cx='235' cy='125' r='6' fill='#334155'/>
  </g>
  <text x='70' y='250' font-size='16' fill='#334155'>{concept}（静态示意）</text>
</svg>"""
        out_dir = storage.diagrams_dir(book_id) / "files"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{cache_key}.svg").write_text(svg, encoding="utf-8")
        return f"files/{cache_key}.svg"

    # 真实文生图服务：CogView（OpenAI 兼容 images/generations）
    import httpx

    cfg = getattr(t2i_backend, "config", {})
    endpoint = str(cfg.get("endpoint", "")).rstrip("/")
    api_key = str(cfg.get("api_key", ""))
    model = str(cfg.get("model", "cogview-3-plus"))
    prompt = f"经济学概念示意插图：{concept}。扁平风格，浅色背景，简洁标注。"
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{endpoint}/images/generations",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "prompt": prompt},
        )
        resp.raise_for_status()
        url = resp.json()["data"][0]["url"]
        img = await client.get(url)
        img.raise_for_status()
    out_dir = storage.diagrams_dir(book_id) / "files"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{cache_key}.png").write_bytes(img.content)
    return f"files/{cache_key}.png"
