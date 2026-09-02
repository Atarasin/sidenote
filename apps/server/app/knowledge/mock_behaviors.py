"""离线 mock 的确定性生成行为（按 purpose 分发）。

真实模型路径由 prompt 约束输出；mock 路径解析 prompt 中的结构化标记
（【章节内容】…【/章节内容】等），用抽取式方法生成等价形态的结果，
保证：引用天然真实（来自原文）、无据必拒答（检索不到就拒绝）。
"""

from __future__ import annotations

import json
import re

from ..llm.types import ChatMessage, Role

_SUMMARY_MIN = 200
_SUMMARY_MAX = 400


def _block(messages: list[ChatMessage], tag: str) -> str:
    """提取 prompt 中 【tag】…【/tag】 标记块的内容。"""
    for m in messages:
        match = re.search(rf"【{tag}】(.*?)【/{tag}】", m.content, re.S)
        if match:
            return match.group(1).strip()
    return ""


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？；])\s*", text)
    return [p.strip() for p in parts if p.strip()]


def chapter_summary(messages: list[ChatMessage], _role: Role, _purpose: str) -> str:
    content = _block(messages, "章节内容")
    if not content:
        return "（离线模式无法提取章节内容）"
    sents = _sentences(content)
    # 抽取式摘要：句首 + 顺次补句，凑到 200~400 字
    out: list[str] = []
    length = 0
    for sent in sents:
        if length >= _SUMMARY_MIN:
            break
        out.append(sent)
        length += len(sent)
    summary = "".join(out)
    if len(summary) > _SUMMARY_MAX:
        summary = summary[:_SUMMARY_MAX]
    return f"本章要点：{summary}" if not summary.startswith("本章") else summary


def glossary(messages: list[ChatMessage], _role: Role, _purpose: str) -> str:
    """「X 是…」「X 指…」定义句模式抽取术语表，输出 JSON。"""
    content = _block(messages, "章节内容")
    terms: dict[str, str] = {}
    for sent in _sentences(content):
        m = re.match(r"(.{2,12}？?)(?:是|指|是指|衡量|描述|展示了?)(.{6,})", sent)
        if m:
            term = m.group(1).strip()
            if term and term not in terms:
                terms[term] = sent
    items = [{"term": t, "definition": d} for t, d in list(terms.items())[:8]]
    return json.dumps(items, ensure_ascii=False)


def dispatch(messages: list[ChatMessage], role: Role, purpose: str) -> str:
    if purpose == "chapter_summary":
        return chapter_summary(messages, role, purpose)
    if purpose == "glossary":
        return glossary(messages, role, purpose)
    return f"（离线模式：未配置模型 API key，purpose={purpose}）"
