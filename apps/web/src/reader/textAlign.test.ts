import { describe, expect, it } from "vitest";
import { alignBlocksToParas, groupItemsByParas, normalizeParaText } from "./textAlign";

describe("normalizeParaText", () => {
  it("mirrors backend normalization", () => {
    expect(normalizeParaText("  供给\u00a0 与\u200b需求  ")).toBe("供给 与 需求");
  });
});

describe("alignBlocksToParas", () => {
  it("aligns identical sequences", () => {
    const r = alignBlocksToParas(
      ["第一章 供给", "供给描述生产者行为。", "需求描述消费者行为。"],
      ["第一章 供给", "供给描述生产者行为。", "需求描述消费者行为。"],
    );
    expect(r).toEqual([0, 1, 2]);
  });

  it("tolerates extra rendered blocks by skipping them", () => {
    const r = alignBlocksToParas(
      ["封面装饰文本", "第一章 供给", "正文段落。"],
      ["第一章 供给", "正文段落。"],
    );
    expect(r).toEqual([null, 0, 1]);
  });

  it("handles a paragraph split across two blocks (prefix consumption)", () => {
    const r = alignBlocksToParas(
      ["长段落的前半", "后半部分续上。", "下一段。"],
      ["长段落的前半后半部分续上。", "下一段。"],
    );
    expect(r).toEqual([0, 0, 1]);
  });
});

describe("groupItemsByParas", () => {
  it("assigns item runs to paragraphs in order", () => {
    const items = [
      { str: "供给是生产者" },
      { str: " 愿意出售的量。" },
      { str: "需求是消费者愿意购买的量。" },
    ];
    const { groups, leftover } = groupItemsByParas(items, [
      "供给是生产者愿意出售的量。",
      "需求是消费者愿意购买的量。",
    ]);
    expect(groups.get(0)).toEqual([0, 1]);
    expect(groups.get(1)).toEqual([2]);
    expect(leftover).toEqual([]);
  });

  it("leaves cross-page carry-over text as leftover", () => {
    // 页首是上一段遗留的尾巴，随后才是本页第一段
    const items = [{ str: "上一段的尾巴。" }, { str: "本页第一段正文。" }];
    const { groups, leftover } = groupItemsByParas(items, ["本页第一段正文。"]);
    expect(groups.get(0)).toEqual([1]);
    expect(leftover).toEqual([0]);
  });

  it("skips paragraphs not present on this page", () => {
    const items = [{ str: "只有这一段。" }];
    const { groups } = groupItemsByParas(items, ["不在本页的段落。", "只有这一段。"]);
    expect(groups.has(0)).toBe(false);
    expect(groups.get(1)).toEqual([0]);
  });
});
