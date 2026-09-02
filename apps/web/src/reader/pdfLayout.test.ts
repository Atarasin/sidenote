import { describe, expect, it } from "vitest";
import { type ItemGeometry, spanOffset, unionBox } from "./pdfLayout";

/** 回归防护：多 item 段落的 span 不得堆叠在段落盒 (0,0)（第 1 轮评审 E1）。 */
describe("pdfLayout", () => {
  const g = (left: number, top: number, w = 40, h = 12): ItemGeometry => ({
    left,
    top,
    right: left + w,
    bottom: top + h,
    fontHeight: h,
  });

  it("unionBox covers all items", () => {
    const u = unionBox([g(100, 200), g(300, 260, 50, 12)]);
    expect(u).toEqual({ left: 100, top: 200, right: 350, bottom: 272 });
  });

  it("span offsets keep absolute position (multi-item paragraph)", () => {
    const geometries = [g(100, 200), g(150, 200), g(100, 216)];
    const u = unionBox(geometries);
    // 盒原点 = (100, 200)；第二个 item 偏移应为 (50, 0) 而非 (0, 0)
    expect(spanOffset(geometries[0], u)).toEqual({ left: 0, top: 0 });
    expect(spanOffset(geometries[1], u)).toEqual({ left: 50, top: 0 });
    expect(spanOffset(geometries[2], u)).toEqual({ left: 0, top: 16 });
    // 不变量：盒原点 + 偏移 === item 绝对坐标
    for (const item of geometries) {
      const off = spanOffset(item, u);
      expect(u.left + off.left).toBe(item.left);
      expect(u.top + off.top).toBe(item.top);
    }
  });
});
