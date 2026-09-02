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


_PARA_LINE = re.compile(r"^\[([a-z0-9-]+)\]\s*(.+)$", re.M)
_QA_HIT_THRESHOLD = 1  # 关键词 bigram 命中数下限（bigram 本身特异性足以挡住无关问题）


_QUESTION_WORDS = (
    "是什么意思",
    "指的是",
    "是什么",
    "有什么用",
    "怎么",
    "如何",
    "为什么",
    "哪些",
    "什么时候",
    "什么",
    "请问",
    "一下",
    "书中",
    "全书",
    "的意思",
    "定义",
    "是指",
    "吗",
    "呢",
    "讲讲",
    "谈谈",
)

# 单字虚词/动词尾巴（在内容段边缘常见）
_PARTICLE_CHARS = "的了吗呢吧是在和与对把被从讲说谈怎给跟有"


def _content_segments(question: str) -> list[str]:
    """去掉疑问虚词与常见单字虚词后的内容段（≥2 字）；同话题判定用整段子串匹配，
    避免跨词 bigram（如「相对」）或被疑问词截断的 n-gram 误命中。"""
    cleaned = re.sub(r"[\s\W]+", "", question)
    for word in _QUESTION_WORDS:
        cleaned = cleaned.replace(word, " ")
    cleaned = "".join(ch if ch not in _PARTICLE_CHARS else " " for ch in cleaned)
    segments = [seg for seg in cleaned.split() if len(seg) >= 2]
    return segments


def qa(messages: list[ChatMessage], _role: Role, _purpose: str) -> str:
    """离线检索式问答：在上下文段落中按问题关键词找依据段落。

    引用的 quote 取该段落的完整原句 → 引用校验必然通过（红线 2 的 mock 侧保证）。
    找不到依据 → hasBasis=false（无据拒答语义与真实模型一致）。
    """
    corpus = ""
    for m in messages:
        corpus += m.content
    question = ""
    # 单行匹配（不带 re.S）：问题行之后还拼有输出格式说明，不能吞进来
    q_match = re.search(r"【问题】(.+)", corpus)
    if q_match:
        question = q_match.group(1).strip()

    paras: list[tuple[str, str]] = _PARA_LINE.findall(corpus)
    segments = _content_segments(question)
    scored: list[tuple[int, str, str]] = []
    for para_id, text in paras:
        hits = sum(len(seg) for seg in segments if seg in text)
        scored.append((hits, para_id, text))
    scored.sort(key=lambda x: x[0], reverse=True)

    top = [item for item in scored if item[0] >= _QA_HIT_THRESHOLD][:2]
    if not top or not question:
        return json.dumps(
            {"answer": "书中未涉及", "citations": [], "hasBasis": False}, ensure_ascii=False
        )

    cites = [{"paraId": pid, "quote": text} for _score, pid, text in top]
    answer = "根据原文：" + "；".join(text for _s, _p, text in top)
    return json.dumps(
        {"answer": answer, "citations": cites, "hasBasis": True}, ensure_ascii=False
    )


def _svg_component(concept: str, simple: bool) -> str:
    """确定性教学 SVG：透明背景 + currentColor，满足沙箱与双容器配色约束。"""
    font = 15 if simple else 13
    return (
        "<!DOCTYPE html><html><head><style>"
        "html,body{background:transparent;margin:0}"
        ".wrap{color:currentColor;font-family:system-ui,sans-serif}"
        "</style></head><body><div class='wrap' style='padding:8px'>"
        f"<svg viewBox='0 0 320 180' width='100%' style='color:currentColor'>"
        "<g fill='none' stroke='currentColor' stroke-width='2'>"
        "<line x1='40' y1='160' x2='300' y2='160'/>"
        "<line x1='40' y1='20' x2='40' y2='160'/>"
        "<line x1='70' y1='50' x2='270' y2='140'/>"
        "<line x1='70' y1='140' x2='270' y2='50' stroke-dasharray='6 4'/>"
        "<circle cx='170' cy='95' r='5' fill='currentColor'/>"
        "</g>"
        f"<text x='50' y='175' font-size='{font}' fill='currentColor'>{concept}</text>"
        "<text x='120' y='105' font-size='12' fill='currentColor'>均衡点</text>"
        "</svg></div>"
        "<script>parent.postMessage({type:'sidenote:ready',hasContent:true},'*');</script>"
        "</body></html>"
    )


def diagram(messages: list[ChatMessage], _role: Role, purpose: str) -> str:

    content = _block(messages, "段落内容")
    concept = "概念"
    m = re.search(r"概念：(.+)", "".join(x.content for x in messages))
    if m:
        concept = m.group(1).splitlines()[0].strip()
    para_id = ""
    pid = re.search(r"【段落内容】（([a-z0-9\-]+)）", "".join(x.content for x in messages))
    if pid:
        para_id = pid.group(1)
    sentence = _sentences(content)[0] if _sentences(content) else ""
    # 去掉 prompt 携带的段落编号前缀，保证 quote 与段落原文逐字一致
    sentence = re.sub(r"^（[a-z0-9-]+）", "", sentence)
    component = _svg_component(concept, simple=purpose == "diagram_repair")
    return json.dumps(
        {
            "componentHtml": component,
            "summary": f"{concept}：曲线交点即均衡（静态示意）",
            "citations": [{"paraId": para_id, "quote": sentence}] if para_id and sentence else [],
        },
        ensure_ascii=False,
    )


def diagram_explain(messages: list[ChatMessage], _role: Role, _purpose: str) -> str:
    content = _block(messages, "段落内容")
    sents = _sentences(content)
    return "".join(sents[:2])[:120] or "（离线模式讲解）"


def dispatch(messages: list[ChatMessage], role: Role, purpose: str) -> str:
    if purpose == "chapter_summary":
        return chapter_summary(messages, role, purpose)
    if purpose == "glossary":
        return glossary(messages, role, purpose)
    if purpose == "qa":
        return qa(messages, role, purpose)
    if purpose in ("diagram", "diagram_repair"):
        return diagram(messages, role, purpose)
    if purpose == "diagram_explain":
        return diagram_explain(messages, role, purpose)
    return f"（离线模式：未配置模型 API key，purpose={purpose}）"
