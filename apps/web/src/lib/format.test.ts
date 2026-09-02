import { describe, expect, it } from "vitest";
import { formatBytes, parseStatusLabel } from "./format";

describe("formatBytes", () => {
  it("renders human readable sizes", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(formatBytes(3 * 1024 * 1024)).toBe("3.0 MB");
    expect(formatBytes(1.5 * 1024 ** 3)).toBe("1.50 GB");
  });
});

describe("parseStatusLabel", () => {
  it("maps backend states to zh labels", () => {
    expect(parseStatusLabel("success")).toBe("可阅读");
    expect(parseStatusLabel("failed")).toBe("解析失败");
  });
});
