import { describe, expect, it } from "vitest";
import { composeSandboxDoc, stripComponentCsp } from "./sandboxDoc";

const FULL_DOC = `<!DOCTYPE html><html><head>
<meta charset="utf-8">
<style>line { stroke: currentColor; }</style>
<script>function anim() { requestAnimationFrame(anim); }</script>
</head><body><svg id="c"></svg></body></html>`;

describe("composeSandboxDoc", () => {
  it("保留组件 head 中的 style/script（评审 D3：只取 body 会剥掉真实模型的样式与动画）", () => {
    const doc = composeSandboxDoc(FULL_DOC, "#1f2937");
    expect(doc).toContain("stroke: currentColor");
    expect(doc).toContain("requestAnimationFrame");
    expect(doc).toContain('<svg id="c"></svg>');
  });

  it("注入 CSP 断网与 :root 配色（评审 D5：sandbox 属性并不禁网络）", () => {
    const doc = composeSandboxDoc(FULL_DOC, "#e2e8f0");
    expect(doc).toContain("Content-Security-Policy");
    expect(doc).toContain("default-src 'none'");
    expect(doc).toContain(":root { color: #e2e8f0; }");
  });

  it("剥掉组件自带的 CSP meta（防止反制包装层检测脚本）", () => {
    const hostile = FULL_DOC.replace(
      '<meta charset="utf-8">',
      '<meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="script-src none">',
    );
    expect(stripComponentCsp('<meta http-equiv="Content-Security-Policy" content="x">')).toBe("");
    const doc = composeSandboxDoc(hostile, "#1f2937");
    expect(doc).not.toContain("script-src none");
    // 只剥 CSP meta，其余 head 内容保留
    expect(doc).toContain("stroke: currentColor");
  });

  it("无 body 标签的片段整体视作 body（mock 组件契约）", () => {
    const doc = composeSandboxDoc("<svg><text>均衡点</text></svg>", "#1f2937");
    expect(doc).toContain("<body><svg><text>均衡点</text></svg></body>");
    expect(doc).toContain("sidenote:ready"); // 检测脚本仍在
  });

  it("组件 head 追加在包装检测脚本之后（检测先安装，错误才能捕获）", () => {
    const doc = composeSandboxDoc(FULL_DOC, "#1f2937");
    const detectAt = doc.indexOf("sidenote:ready");
    const componentScriptAt = doc.indexOf("requestAnimationFrame");
    expect(detectAt).toBeGreaterThanOrEqual(0);
    expect(detectAt).toBeLessThan(componentScriptAt);
  });
});
