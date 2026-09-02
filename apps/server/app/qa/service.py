"""引用式问答（计划 Slice 1.5 / 上游 §3.3，红线 2 的执行载体）。

链路：装配混合式上下文 → 模型作答（JSON：answer + citations + hasBasis）
→ 引用真实性校验（quote 必须能在对应 paraId 段落中字面对上）
→ 校验不过则丢弃并重答一次；仍无有效引用 → 无据拒答「书中未涉及」。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from ..knowledge.builder import build_book_knowledge
from ..knowledge.context import assemble_messages, chapter_block
from ..knowledge.models import BookKnowledge, load_knowledge
from ..knowledge.retrieval import needs_witness, retrieve
from ..llm.errors import ModelError
from ..llm.types import ChatMessage

ANSWER_FORMAT_INSTRUCTION = (
    "\n请严格按 JSON 输出："
    '{"answer":"回答正文","citations":[{"paraId":"段落编号","quote":"原文逐字引用"}],'
    '"hasBasis":true或false}。'
    "citations 的 quote 必须逐字来自对应段落编号的原文；书中无依据时 hasBasis=false、"
    'citations=[]，answer 写「书中未涉及」。'
)


@dataclass
class Citation:
    paraId: str
    quote: str


@dataclass
class AskResult:
    answer: str
    citations: list[Citation] = field(default_factory=list)
    hasBasis: bool = False
    witnessUsed: bool = False
    chapterId: str | None = None
    provider: str = ""
    retried: bool = False


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text)


def validate_citations(
    doc,
    citations: list[dict],
) -> list[Citation]:
    """T1.5.2 引用真实性校验：paraId 存在 + quote 归一化后字面包含于该段原文。"""
    para_text = {p.id: _norm(p.text) for ch in doc.chapters for p in ch.paras}
    valid: list[Citation] = []
    for item in citations or []:
        para_id = str(item.get("paraId", "")).strip()
        quote = str(item.get("quote", "")).strip()
        if not para_id or not quote:
            continue
        source = para_text.get(para_id)
        if source and _norm(quote) in source:
            valid.append(Citation(paraId=para_id, quote=quote))
    return valid


def _parse_answer_json(content: str) -> dict | None:
    """容错解析模型输出的 JSON（允许 markdown 代码块包裹）。"""
    text = content.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
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


async def answer_question(
    storage,
    usage_log,
    backend,
    book_id: str,
    question: str,
    chapter_id: str | None = None,
) -> AskResult:
    doc = storage.read_bookdoc(book_id)
    if doc is None:
        raise FileNotFoundError(f"书籍未解析：{book_id}")

    knowledge: BookKnowledge | None = load_knowledge(storage, book_id)
    if knowledge is None:
        knowledge = await build_book_knowledge(storage, book_id, backend)

    # 跨章判定 → 旁证装载（T1.4.2 与问答链路在此汇合）
    current_text = ""
    if chapter_id:
        for line in chapter_block(doc, chapter_id).splitlines():
            current_text += re.sub(r"^\[[^\]]+\]\s*", "", line)
    witness_paras: list[dict] = []
    if needs_witness(question, current_text):
        # 命中的块展开为段落行（引用按段落粒度校验，上下文与校验口径一致）
        para_by_id = {p.id: p for ch in doc.chapters for p in ch.paras}
        for chunk in retrieve(storage, book_id, question, exclude_chapter=chapter_id):
            for pid in chunk.get("paraIds", []):
                para = para_by_id.get(pid)
                if para is not None and len(witness_paras) < 12:
                    witness_paras.append({"id": para.id, "text": para.text})

    base_messages = assemble_messages(
        knowledge, doc, question, chapter_id=chapter_id, witness_chunks=witness_paras
    )

    result = AskResult(answer="", chapterId=chapter_id, provider=getattr(backend, "provider", ""))
    last_content = ""
    for attempt in range(2):  # 首答 + 校验失败重答一次
        messages = list(base_messages)
        if attempt == 1:
            feedback = (
                "你上一轮的引用无法在原文中逐字对上，已被丢弃。"
                "请重新回答，引用必须逐字来自上文段落原文。"
            )
            messages = [
                messages[0],
                ChatMessage("assistant", last_content),
                ChatMessage("user", feedback + ANSWER_FORMAT_INSTRUCTION),
            ]
        else:
            messages = [
                messages[0],
                ChatMessage("user", messages[1].content + ANSWER_FORMAT_INSTRUCTION),
            ]
        try:
            response = await backend.chat(
                "long_text_qa", messages, book_id=book_id, purpose="qa"
            )
        except ModelError as exc:
            result.answer = f"模型调用失败（{exc.kind}），请稍后重试。"
            return result
        last_content = response.content
        data = _parse_answer_json(response.content)
        if data is None:
            continue  # 解析失败 → 重答一次
        citations = validate_citations(doc, data.get("citations") or [])
        has_basis = bool(data.get("hasBasis"))
        result.retried = attempt == 1
        if has_basis and citations:
            result.answer = str(data.get("answer", "")).strip()
            result.citations = citations
            result.hasBasis = True
            result.witnessUsed = bool(witness_paras)
            return result
        if has_basis and not citations:
            continue  # 声称有据但引用全部不实 → 丢弃并重答（T1.5.2）
        # hasBasis=false → 无据拒答（T1.5.3）
        result.answer = "书中未涉及"
        result.citations = []
        result.hasBasis = False
        result.witnessUsed = bool(witness_paras)
        return result

    # 两次都无法产出「有据且引用真实」的回答 → 按无据处理
    result.answer = "书中未涉及"
    result.hasBasis = False
    result.witnessUsed = bool(witness_paras)
    return result
