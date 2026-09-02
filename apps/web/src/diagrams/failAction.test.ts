import { describe, expect, it } from "vitest";
import { sandboxFailAction } from "./failAction";

describe("sandboxFailAction（评审 D2：失败处置封顶，杜绝修复死循环）", () => {
  it("第 1 次失败 → 修复重试（T2.2.3）", () => {
    expect(sandboxFailAction(1)).toBe("repair");
  });

  it("第 2 次起（修复返回同一坏组件再失败等）→ 一律降级（T2.3.2）", () => {
    expect(sandboxFailAction(2)).toBe("degrade");
    expect(sandboxFailAction(3)).toBe("degrade");
  });
});
