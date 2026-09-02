/**
 * 沙箱渲染容器（计划 T2.2.1 / T2.2.2，上游 §3.4 R2 规避）。
 *
 * - sandbox="allow-scripts"（无 allow-same-origin）：脚本无法逃逸读父页面；
 *   网络访问由包装层 CSP default-src 'none' 阻断（见 sandboxDoc.ts，评审 D5）。
 * - 渲染失败检测：注入包装脚本捕获 window.onerror + 加载后自检可见内容，
 *   通过 postMessage 上报 sidenote:ready / sidenote:error；6 秒无消息判超时。
 * - 双容器配色（UI §3.4 / U-R2）：包装注入 :root{color}，组件内 currentColor 随容器亮暗自适应。
 * - ready 之后的迟到 error 不再回退失败态（settled 守卫，评审 D7）。
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { composeSandboxDoc } from "./sandboxDoc";

interface Props {
  html: string;
  color: string;
  onReady?: (hasContent: boolean) => void;
  onFail?: (reason: string) => void;
  timeoutMs?: number;
  title?: string;
}

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

  const srcDoc = useMemo(() => composeSandboxDoc(html, color), [html, color]);

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
      if (settled) return; // ready/error 已定，迟到消息（如运行期报错）不再翻转状态
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
      <div
        className="flex h-full items-center justify-center rounded-lg border border-dashed p-4 text-xs opacity-70"
        style={{ color, borderColor: color }}
      >
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
