/**
 * 沙箱文档组装（T2.2.1 / 评审 D3、D5）。
 *
 * - 保留组件 <head> 中的 <style>/<script>（真实模型常把样式/脚本放 head，
 *   只取 body 会把交互动画剥掉）；
 * - 剥掉组件自带的 CSP meta（防止组件反过来锁死我们的检测脚本）；
 * - 包装层注入自己的 CSP：default-src 'none' 断网（sandbox 属性并不禁网络），
 *   只放行内联脚本/样式与 data: 资源；
 * - 注入 :root{color} 让组件 currentColor 随容器亮暗自适应（UI §3.4 双容器配色）。
 */

const CSP =
  "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; " +
  "img-src data: blob:; font-src data:; media-src data: blob:; connect-src 'none'";

export const SANDBOX_READY_CONTRACT = "sidenote:ready";

export function wrapperHead(color: string): string {
  return `<!DOCTYPE html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="${CSP}">
<style>
  :root { color: ${color}; }
  html, body { background: transparent; margin: 0; }
  body { font-family: system-ui, -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; }
</style>
<script>
(function () {
  var posted = false;
  function report(type, payload) {
    if (posted && type === "${SANDBOX_READY_CONTRACT}") return;
    if (type === "${SANDBOX_READY_CONTRACT}") posted = true;
    try { parent.postMessage(Object.assign({ type: type }, payload || {}), "*"); } catch (e) {}
  }
  window.addEventListener("error", function (e) {
    report("sidenote:error", { reason: "脚本错误：" + (e.message || "unknown") });
  });
  window.addEventListener("unhandledrejection", function (e) {
    report("sidenote:error", { reason: "异步错误：" + String(e.reason).slice(0, 120) });
  });
  function selfCheck() {
    var visible = false;
    try {
      var el = document.body;
      visible = !!el && (
        el.querySelectorAll("svg,canvas,img,video").length > 0 ||
        (el.innerText || "").trim().length > 0
      );
    } catch (e) { visible = false; }
    report("${SANDBOX_READY_CONTRACT}", { hasContent: visible });
  }
  if (document.readyState === "complete") {
    setTimeout(selfCheck, 250);
  } else {
    window.addEventListener("load", function () { setTimeout(selfCheck, 250); });
  }
})();
</script>`;
}

/** 剥掉组件文档里自带的 CSP meta（会反制包装层检测脚本）。 */
export function stripComponentCsp(head: string): string {
  return head.replace(/<meta[^>]+http-equiv\s*=\s*["']?content-security-policy[^>]*>/gi, "");
}

/** 组装完整沙箱文档：包装 head（CSP/配色/检测脚本）+ 组件 head + 组件 body。 */
export function composeSandboxDoc(html: string, color: string): string {
  const headMatch = html.match(/<head[^>]*>([\s\S]*)<\/head>/i);
  const bodyMatch = html.match(/<body[^>]*>([\s\S]*)<\/body>/i);
  const componentHead = headMatch ? stripComponentCsp(headMatch[1]) : "";
  const componentBody = bodyMatch ? bodyMatch[1] : html;
  return `${wrapperHead(color)}${componentHead}</head><body>${componentBody}</body></html>`;
}
