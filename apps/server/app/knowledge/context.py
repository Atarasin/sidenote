"""上下文装配（计划 Slice 1.3 / 上游 §3.2 混合式，决策 D2）。

- 常驻上下文（T1.3.1）：全书摘要 + 目录地图 + 术语表，作为每轮固定前缀。
- 动态装载（T1.3.2）：当前阅读章节全文进上下文，切换章节时替换。
- 服务商上下文缓存（T1.3.3）：常驻前缀字节级稳定（同一本书每轮完全一致），
  动态部分拼在其后 → DeepSeek/Kimi/GLM 的前缀缓存自动对齐；
  命中量由 usage 日志的 cacheHitTokens 承载（红线 3 / R3 规避）。

消息结构（顺序固定，保证前缀缓存）：
  [0] system   = 常驻前缀（目录地图 + 术语表 + 各章摘要）
  [1] user     = 【当前章节】… + 【旁证】… + 【问题】…
"""

from __future__ import annotations

from ..llm.types import ChatMessage
from .models import BookKnowledge

QA_SYSTEM_HEAD = (
    "你是严谨的学术阅读助理，只依据提供的书中内容回答。"
    "引用时使用行首方括号内的段落编号（如 [c001-p0003]），引用原文必须逐字。"
    "书中没有依据时必须明确回答「书中未涉及」，禁止编造。\n\n"
)


def resident_prefix(knowledge: BookKnowledge) -> str:
    """常驻上下文（每轮固定前缀；同一本书字节级一致以命中前缀缓存）。"""
    parts = ["【目录地图】"]
    parts.extend(knowledge.tocMap or [])
    if knowledge.glossary:
        parts.append("\n【术语表】")
        for term in knowledge.glossary:
            parts.append(f"- {term.term}：{term.definition}")
    parts.append("\n【各章摘要】")
    for chapter in knowledge.chapters:
        if chapter.status == "ok" and chapter.summary:
            parts.append(f"{chapter.title}：{chapter.summary}")
    return QA_SYSTEM_HEAD + "\n".join(parts)


def chapter_block(doc, chapter_id: str) -> str:
    """当前章节全文（T1.3.2）：每段带 [paraId] 前缀，供模型引用。"""
    chapter = next((c for c in doc.chapters if c.id == chapter_id), None)
    if chapter is None:
        return ""
    lines = [f"【当前章节：{chapter.title}】"]
    lines.extend(f"[{p.id}] {p.text}" for p in chapter.paras)
    return "\n".join(lines)


def witness_block(paras: list[dict]) -> str:
    """旁证段落（T1.4.2 装载进上下文）：[{id, text}] 逐段 [paraId] 行，与当前章节同格式，
    引用校验与 mock 检索对两种上下文一视同仁。"""
    if not paras:
        return ""
    lines = ["【其他章节旁证】"]
    lines.extend(f"[{p['id']}] {p['text']}" for p in paras)
    return "\n".join(lines)


def assemble_messages(
    knowledge: BookKnowledge,
    doc,
    question: str,
    *,
    chapter_id: str | None = None,
    witness_chunks: list[dict] | None = None,
) -> list[ChatMessage]:
    """装配一轮问答的完整消息（常驻前缀固定 → 前缀缓存命中）。"""
    user_parts: list[str] = []
    if chapter_id:
        block = chapter_block(doc, chapter_id)
        if block:
            user_parts.append(block)
    if witness_chunks:
        user_parts.append(witness_block(witness_chunks))
    user_parts.append(f"【问题】{question}")
    return [
        ChatMessage("system", resident_prefix(knowledge)),
        ChatMessage("user", "\n\n".join(user_parts)),
    ]
