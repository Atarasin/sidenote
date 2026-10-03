import type { BookDoc, Para, TocItem } from "@shared/types/bookdoc";

/**
 * 目录项 → PDF 跳转落点（纯函数，可单测）。
 *
 * 解析器会丢弃「重组不出段落」的章节，目录若仍保留指向它们的条目，就是悬空引用：
 * 此时返回 null，由调用方给出可见提示——不允许静默什么都不做（M0 缺陷 #14）。
 */

export interface TocTarget {
  paraId: string;
  page: number;
}

export function resolveTocTarget(doc: BookDoc, toc: TocItem): TocTarget | null {
  const anchored = toc.paraId ? findPara(doc, toc.paraId) : undefined;
  if (anchored?.page != null) return { paraId: anchored.id, page: anchored.page };
  // 章级目录项（paraId 为空或已失效）：落到本章第一个带页码的段落
  const chapter = doc.chapters.find((c) => c.id === toc.chapterId);
  const first = chapter?.paras.find((p) => p.page != null);
  if (first?.page != null) return { paraId: first.id, page: first.page };
  return null;
}

function findPara(doc: BookDoc, paraId: string): Para | undefined {
  for (const chapter of doc.chapters) {
    const hit = chapter.paras.find((p) => p.id === paraId);
    if (hit) return hit;
  }
  return undefined;
}
