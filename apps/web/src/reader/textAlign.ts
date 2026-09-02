/**
 * 渲染层锚点对齐（计划 T0.3.3）：把渲染产出的 DOM 文本与 BookDoc 段落一一对应。
 * 归一化规则与后端 app/books/text_utils.py 保持一致。
 */

/** 与后端 normalize_text 对应：NFC、去零宽、压空白。 */
export function normalizeParaText(raw: string): string {
  return raw
    .normalize("NFC")
    .replace(/[\u200b\ufeff\u00a0]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/** 匹配用：去掉全部空白（中英文混排下空格不可靠）。 */
function stripWs(s: string): string {
  return s.replace(/\s+/g, "");
}

/**
 * EPUB 锚点对齐：块级元素文本序列 ↔ 段落文本序列。
 * 返回 blocks[i] 对应的段落下标（null = 无法对应）。
 * 规则：从当前段落起尝试前缀消费；块文本通常是段落文本的完整或前缀形式。
 */
export function alignBlocksToParas(blockTexts: string[], paraTexts: string[]): (number | null)[] {
  const blocks = blockTexts.map((t) => stripWs(normalizeParaText(t)));
  const paras = paraTexts.map((t) => stripWs(normalizeParaText(t)));
  const out: (number | null)[] = new Array(blocks.length).fill(null);
  let j = 0;
  let consumed = 0; // paras[j] 内已被消费的字符数

  const remainderOf = (idx: number) => paras[idx]?.slice(consumed) ?? "";
  for (let i = 0; i < blocks.length; i++) {
    const b = blocks[i];
    if (!b) continue;
    // 快速路径：当前段落剩余部分以该块开头（块 = 段落全文或其前缀）
    if (remainderOf(j).startsWith(b)) {
      out[i] = j;
      consumed += b.length;
      continue;
    }
    // 渲染层多出的块：在有界窗口内向后找能容纳它的段落（当前段可能整体被解析丢弃）
    let found = -1;
    for (let k = j + 1; k < Math.min(j + 5, paras.length); k++) {
      if (paras[k].startsWith(b)) {
        found = k;
        break;
      }
    }
    if (found !== -1) {
      j = found;
      consumed = b.length;
      out[i] = j;
    } else {
      out[i] = null; // 无法对应任何段落，不标注
    }
  }
  return out;
}

export interface TextItemLike {
  str: string;
}

export interface ParaGroupResult {
  /** paraIdx → 属于该段的 item 下标列表 */
  groups: Map<number, number[]>;
  /** 未归属任何段落的 item 下标（跨页延续的前半段、图表散字等） */
  leftover: number[];
}

/**
 * PDF 锚点对齐：页面文本 item 流 ↔ 段落文本。
 * 以「去空白字符流」上的子串查找实现：从上次消费位置向后找段落全文，
 * 命中则把覆盖到的 item 归入该段；未命中该段放弃锚定（保持有界回退）。
 */
export function groupItemsByParas(
  items: TextItemLike[],
  paraTexts: string[],
  searchWindow = 300,
): ParaGroupResult {
  const groups = new Map<number, number[]>();
  const leftover: number[] = [];

  // 构建去空白字符流：chars[k] = { ch, itemIdx }
  const chars: { ch: string; itemIdx: number }[] = [];
  for (let idx = 0; idx < items.length; idx++) {
    const s = items[idx].str.replace(/\s+/g, "");
    for (const ch of s) chars.push({ ch, itemIdx: idx });
  }
  const stream = chars.map((c) => c.ch).join("");

  let cursor = 0;
  for (let paraIdx = 0; paraIdx < paraTexts.length; paraIdx++) {
    const para = paraTexts[paraIdx];
    const t = stripWs(normalizeParaText(para));
    if (!t) continue;
    const k = stream.indexOf(t, cursor);
    if (k === -1 || k > cursor + searchWindow) {
      continue; // 本段在该页无完整对应（跨页断开等），不锚定
    }
    const end = k + t.length;
    const itemIdxs: number[] = [];
    for (let c = k; c < end; c++) {
      const idx = chars[c].itemIdx;
      if (itemIdxs.length === 0 || itemIdxs[itemIdxs.length - 1] !== idx) {
        itemIdxs.push(idx);
      }
    }
    groups.set(paraIdx, itemIdxs);
    cursor = end;
  }

  const grouped = new Set<number>();
  for (const idxs of groups.values()) {
    for (const i of idxs) grouped.add(i);
  }
  for (let idx = 0; idx < items.length; idx++) {
    if (!grouped.has(idx)) leftover.push(idx);
  }
  return { groups, leftover };
}
