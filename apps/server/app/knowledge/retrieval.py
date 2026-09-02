"""旁证检索（计划 Slice 1.4 / 上游 §3.2）。

- 章节分块与向量索引按书持久化（T1.4.1）：knowledge/index.json。
- embedding 选型：本地字符二元组 TF-IDF（登记于上游 §9）——
  零依赖、零成本、书籍内容不出本地（红线 1 最严格解读）。
- 跨章问题流程（T1.4.2）：needs_witness 判定 → retrieve top-k → 装载进上下文。
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter

CHUNK_TARGET_CHARS = 500  # 块目标长度（段落对齐，不切断段落）
CHUNK_MAX_CHARS = 800
TOP_K = 4

_CROSS_CHAPTER_SIGNALS = re.compile(
    r"全书|哪些章|其他章|别的章|各章|比较|对比|总结|归纳|还(?:有|在).*提到|第[一二三四五六七八九十\d]+章"
)

# 停用高频虚词 bigram（对中文检索无区分度）
_STOP_BIGRAMS: set[str] = set()


def _bigrams(text: str) -> Counter:
    cleaned = re.sub(r"[\s\W]+", "", text, flags=re.UNICODE)
    counter: Counter = Counter()
    for i in range(len(cleaned) - 1):
        counter[cleaned[i : i + 2]] += 1
    if cleaned:
        counter[cleaned[-1]] += 1  # 末字一元组保留
    return counter


# ---------- 分块 ----------


def chunk_book(doc) -> list[dict]:
    """按段落拼块（~500 字，段落边界对齐；保留 paraIds 供引用回跳）。"""
    chunks: list[dict] = []
    for chapter in doc.chapters:
        current: dict | None = None
        used = 0
        for para in chapter.paras:
            if current is None or used + len(para.text) > CHUNK_TARGET_CHARS:
                current = {"chapterId": chapter.id, "paraIds": [], "text": ""}
                chunks.append(current)
                used = 0
            current["paraIds"].append(para.id)
            current["text"] += para.text
            used += len(para.text)
    for chunk in chunks:
        chunk["text"] = chunk["text"].strip()
    return [c for c in chunks if c["text"]]


# ---------- 索引 ----------


def build_index(doc) -> dict:
    """构建 TF-IDF（char-bigram）向量索引并序列化为可持久化结构。"""
    chunks = chunk_book(doc)
    doc_freq: Counter = Counter()
    chunk_counters = []
    for chunk in chunks:
        counter = _bigrams(chunk["text"])
        chunk_counters.append(counter)
        doc_freq.update(counter.keys())

    n = max(len(chunks), 1)
    idf = {term: math.log((n + 1) / (df + 1)) + 1.0 for term, df in doc_freq.items()}

    entries = []
    for chunk, counter in zip(chunks, chunk_counters, strict=True):
        vec = {t: tf * idf[t] for t, tf in counter.items() if t not in _STOP_BIGRAMS}
        norm = math.sqrt(sum(w * w for w in vec.values())) or 1.0
        entries.append(
            {
                "chapterId": chunk["chapterId"],
                "paraIds": chunk["paraIds"],
                "text": chunk["text"],
                "norm": norm,
                "vec": vec,
            }
        )
    return {"idf": idf, "chunks": entries}


def save_index(storage, book_id: str, index: dict) -> None:
    path = storage.knowledge_dir(book_id) / "index.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")


def load_index(storage, book_id: str) -> dict | None:
    path = storage.knowledge_dir(book_id) / "index.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_index(storage, book_id: str) -> dict:
    index = load_index(storage, book_id)
    if index is None:
        doc = storage.read_bookdoc(book_id)
        if doc is None:
            raise FileNotFoundError(f"书籍未解析：{book_id}")
        index = build_index(doc)
        save_index(storage, book_id, index)
    return index


# ---------- 检索 ----------


def retrieve(
    storage, book_id: str, query: str, *, k: int = TOP_K, exclude_chapter: str | None = None
) -> list[dict]:
    """top-k 相似块（余弦），可排除当前章（当前章全文已在上下文）。"""
    index = ensure_index(storage, book_id)
    idf = index["idf"]
    q_counter = _bigrams(query)
    q_vec = {t: tf * idf.get(t, 1.0) for t, tf in q_counter.items()}
    q_norm = math.sqrt(sum(w * w for w in q_vec.values())) or 1.0

    scored: list[tuple[float, dict]] = []
    for chunk in index["chunks"]:
        if exclude_chapter and chunk["chapterId"] == exclude_chapter:
            continue
        dot = sum(w * chunk["vec"].get(t, 0.0) for t, w in q_vec.items())
        score = dot / (q_norm * chunk["norm"])
        scored.append((score, chunk))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    top = [dict(chunk, score=round(score, 4)) for score, chunk in scored[:k] if score > 0]
    return top


# ---------- 跨章判定（T1.4.2） ----------


def needs_witness(question: str, current_chapter_text: str) -> bool:
    """判定是否需要旁证：显式跨章信号，或当前章覆盖不了问题关键词。"""
    if _CROSS_CHAPTER_SIGNALS.search(question):
        return True
    keywords = _extract_keywords(question)
    if not keywords:
        return False
    hit = sum(1 for kw in keywords if kw in current_chapter_text)
    return hit / len(keywords) < 0.4


_STOP_KEYWORDS = {"什么", "怎么", "如何", "为什么", "哪些", "请问", "一下", "书中"}


def _extract_keywords(question: str) -> list[str]:
    cleaned = re.sub(r"[\s\W]+", "", question, flags=re.UNICODE)
    bigrams = [cleaned[i : i + 2] for i in range(len(cleaned) - 1)]
    return [b for b in dict.fromkeys(bigrams) if b not in _STOP_KEYWORDS][:8]
