/**
 * 沙箱渲染容器（计划 T2.2.1 / T2.2.2，上游 §3.4 R2 规避）。
 *
 * - sandbox="allow-scripts"：允许组件内动画脚本，但禁止网络访问、禁止同源（脚本无法逃逸读父页面）。
 * - 渲染失败检测：注入包装脚本捕获 window.onerror + DOMContentLoaded 后自检可见内容，
 *   通过 postMessage 上报 sidenote:ready / sidenote:error；6 秒无消息判超时。
 * - 双容器配色（UI §3.4 / U-R2）：包装注入 :root{color}，组件内 currentColor 随容器亮暗自适应。
 */
import { useEffect, useRef, useState } from "react";

interface Props {
  html: string;
  color: string;
  onReady?: (hasContent: boolean) => void;
  onFail?: (reason: string) => void;
  timeoutMs?: number;
  title?: string;
}

const WRAPPER_HEAD = (color: string) => `<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
  :root { color: ${color}; }
  html, body { background: transparent; margin: 0; }
  body { font-family: system-ui, -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; }
</style>
<script>
(function () {
  var posted = false;
  function report(type, payload) {
    if (posted && type === "sidenote:ready") return;
    if (type === "sidenote:ready") posted = true;
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
    report("sidenote:ready", { hasContent: visible });
  }
  if (document.readyState === "complete") {
    setTimeout(selfCheck, 250);
  } else {
    window.addEventListener("load", function () { setTimeout(selfCheck, 250); });
  }
})();
</script></head><body>`;

export default function SandboxFrame({
  html,
  color,
  onReady,
  onFail,
  timeoutMs = 6000,
  title = "图解组件",
}: Props) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [failed, setFailed] = useState(false);

  // 只取组件自身的 <body> 内容，包装脚本/样式由本容器注入（不信任生成代码自觉）
  const bodyMatch = html.match(/<body[^>]*>([\s\S]*)<\/body>/i);
  const componentBody = bodyMatch ? bodyMatch[1] : html;
  const srcDoc = `${WRAPPER_HEAD(color)}${componentBody}</body></html>`;

  // biome-ignore lint/correctness/useExhaustiveDependencies: html/color 变化才重建沙箱；onReady/onFail/timeoutMs 为回调与常量，不参与重建
  useEffect(() => {
    let settled = false;
    const timer = window.setTimeout(() => {
      if (!settled) {
        settled = true;
        setFailed(true);
        onFail?.("渲染超时");
      }
    }, timeoutMs);
    const onMessage = (event: MessageEvent) => {
      if (event.source !== iframeRef.current?.contentWindow) return;
      const data = event.data as { type?: string; hasContent?: boolean; reason?: string };
      if (!data || typeof data.type !== "string") return;
      if (data.type === "sidenote:ready") {
        settled = true;
        window.clearTimeout(timer);
        if (data.hasContent) {
          setFailed(false);
          onReady?.(true);
        } else {
          setFailed(true);
          onFail?.("空渲染");
        }
      } else if (data.type === "sidenote:error") {
        settled = true;
        window.clearTimeout(timer);
        setFailed(true);
        onFail?.(data.reason || "脚本错误");
      }
    };
    window.addEventListener("message", onMessage);
    return () => {
      settled = true;
      window.clearTimeout(timer);
      window.removeEventListener("message", onMessage);
    };
  }, [html, color]);

  if (failed) {
    return (
      <div className="flex h-full items-center justify-center rounded-lg border border-dashed border-stone-300 p-4 text-xs text-stone-400">
        组件渲染失败
      </div>
    );
  }
  return (
    <iframe
      ref={iframeRef}
      title={title}
      sandbox="allow-scripts"
      srcDoc={srcDoc}
      className="h-full w-full border-0 bg-transparent"
      style={{ color }}
    />
  );
}
