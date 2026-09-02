import { describe, expect, it } from "vitest";
import {
  type Point,
  isMeaningfulStroke,
  paraScore,
  rectsIntersect,
  selectionRect,
  strokeBounds,
} from "./geometry";

const ring: Point[] = [
  { x: 100, y: 100 },
  { x: 160, y: 100 },
  { x: 160, y: 160 },
  { x: 100, y: 160 },
  { x: 100, y: 101 },
];

describe("strokeBounds / selectionRect（T3.1.3）", () => {
  it("包围盒取极值", () => {
    const b = strokeBounds(ring);
    expect(b).toEqual({ x: 100, y: 100, width: 60, height: 60 });
  });

  it("空笔迹返回 null", () => {
    expect(strokeBounds([])).toBeNull();
  });

  it("选区 = 包围盒外扩 pad 并裁进容器", () => {
    const sel = selectionRect(ring, 10, 200, 200);
    expect(sel).toEqual({ x: 90, y: 90, width: 80, height: 80 });
  });

  it("越界裁剪：贴近容器边缘时夹在 [0,w]×[0,h]", () => {
    const edge: Point[] = [
      { x: 0, y: 0 },
      { x: 5, y: 5 },
    ];
    const sel = selectionRect(edge, 20, 50, 50);
    expect(sel).toEqual({ x: 0, y: 0, width: 25, height: 25 });
  });
});

describe("isMeaningfulStroke（点按不算圈选）", () => {
  it("拖拽幅度足够 → true", () => {
    expect(isMeaningfulStroke(ring)).toBe(true);
  });
  it("微动/单击 → false", () => {
    expect(
      isMeaningfulStroke([
        { x: 10, y: 10 },
        { x: 12, y: 10 },
      ]),
    ).toBe(false);
    expect(isMeaningfulStroke([{ x: 10, y: 10 }])).toBe(false);
  });
});

describe("候选段落打分（T3.2.2 前端侧）", () => {
  const sel = { x: 90, y: 90, width: 80, height: 80 };
  it("相交得 2 分、近邻得 1 分、远段 0 分", () => {
    const hit = { x: 100, y: 100, width: 60, height: 20 };
    const near = { x: 100, y: 175, width: 60, height: 20 };
    const far = { x: 100, y: 400, width: 60, height: 20 };
    expect(paraScore(hit, sel)).toBe(2);
    expect(paraScore(near, sel)).toBe(1);
    expect(paraScore(far, sel)).toBe(0);
  });
  it("rectsIntersect 边界（相接不算相交）", () => {
    const a = { x: 0, y: 0, width: 10, height: 10 };
    expect(rectsIntersect(a, { x: 10, y: 0, width: 5, height: 5 })).toBe(false);
    expect(rectsIntersect(a, { x: 9, y: 0, width: 5, height: 5 })).toBe(true);
  });
});
