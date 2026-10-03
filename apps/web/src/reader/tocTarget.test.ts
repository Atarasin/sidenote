import type { BookDoc } from "@shared/types/bookdoc";
import { describe, expect, it } from "vitest";
import { resolveTocTarget } from "./tocTarget";

/** 回归防护：目录项指向不存在章节时（解析器丢弃了空章节）不得静默无反应（M0 缺陷 #14）。 */
describe("resolveTocTarget", () => {
  const doc: BookDoc = {
    meta: { bookId: "0".repeat(16), title: "测试书", format: "pdf", fileHash: "f".repeat(8) },
    toc: [],
    figures: [],
    chapters: [
      {
        id: "c001",
        title: "第一章",
        paras: [
          { id: "c001-p0001", text: "甲", page: 0 },
          { id: "c001-p0002", text: "乙", page: 1 },
        ],
      },
      { id: "c003", title: "第三章", paras: [{ id: "c003-p0001", text: "丙", page: 4 }] },
      { id: "c009", title: "第九章", paras: [{ id: "c009-p0001", text: "丁" }] },
    ],
  };

  it("段落锚点优先：落在该段所在页", () => {
    expect(
      resolveTocTarget(doc, {
        id: "toc-002",
        title: "乙",
        chapterId: "c001",
        paraId: "c001-p0002",
      }),
    ).toEqual({ paraId: "c001-p0002", page: 1 });
  });

  it("章级目录项：落到本章第一个带页码的段落", () => {
    expect(resolveTocTarget(doc, { id: "toc-003", title: "第三章", chapterId: "c003" })).toEqual({
      paraId: "c003-p0001",
      page: 4,
    });
  });

  it("悬空章节（解析器已丢弃该章）→ null，交由调用方提示", () => {
    expect(resolveTocTarget(doc, { id: "toc-002", title: "第二章", chapterId: "c002" })).toBeNull();
  });

  it("悬空 paraId 但章节有效 → 回落章内首段", () => {
    expect(
      resolveTocTarget(doc, {
        id: "toc-004",
        title: "第三章",
        chapterId: "c003",
        paraId: "c003-p9999",
      }),
    ).toEqual({ paraId: "c003-p0001", page: 4 });
  });

  it("章节存在但无任何带页码的段落（EPUB 形制）→ null", () => {
    expect(resolveTocTarget(doc, { id: "toc-009", title: "第九章", chapterId: "c009" })).toBeNull();
  });

  it("既无 chapterId 也无 paraId → null", () => {
    expect(resolveTocTarget(doc, { id: "toc-000", title: "空项" })).toBeNull();
  });
});
