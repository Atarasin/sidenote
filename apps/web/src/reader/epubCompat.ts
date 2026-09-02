/**
 * epub.js 运行时兼容层。
 *
 * 1) 自适应 rAF 垫片：epub.js 渲染队列完全依赖 requestAnimationFrame 逐任务推进；
 *    在部分内嵌 WebView（合成器不逐帧回调）与后台标签页中 rAF 停摆，队列会永久卡死
 *    （iframe 永不创建）。垫片同时调度真 rAF 与宏任务，先到先得、只回一次：
 *    rAF 正常时保持原时序，rAF 失效时由 32ms 宏任务兜底。
 *    必须在 epubjs 脚本注入前安装（epubjs 在模块加载期捕获 rAF 引用）。
 * 2) epub.js 加载：ESM 入口在打包器 interop 下问题多，统一走包内自包含 UMD 构建，
 *    以经典 <script> 注入（this=window），其外部依赖 JSZip 需先注入。
 */

import type { Book } from "epubjs";
import epubUmdUrl from "epubjs/dist/epub.min.js?url";
import jszipUmdUrl from "jszip/dist/jszip.min.js?url";

declare global {
  interface Window {
    ePub?: (urlOrData: string | ArrayBuffer, options?: Record<string, unknown>) => Book;
    JSZip?: unknown;
  }
}

let rafShimInstalled = false;

export function installRafShim(): void {
  if (rafShimInstalled || typeof window === "undefined") return;
  const orig =
    typeof window.requestAnimationFrame === "function"
      ? window.requestAnimationFrame.bind(window)
      : null;
  window.requestAnimationFrame = ((cb: FrameRequestCallback): number => {
    let done = false;
    const call = (t: number) => {
      if (done) return;
      done = true;
      cb(t);
    };
    const timer = window.setTimeout(() => call(performance.now()), 32);
    if (orig) {
      orig(() => {
        if (done) return;
        window.clearTimeout(timer);
        call(performance.now());
      });
    }
    return timer;
  }) as typeof window.requestAnimationFrame;
  rafShimInstalled = true;
}

function loadScript(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = src;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error(`脚本加载失败：${src}`));
    document.head.appendChild(script);
  });
}

let epubGlobalPromise: Promise<
  (input: string | ArrayBuffer, options?: Record<string, unknown>) => Book
> | null = null;

export function loadEpubGlobal() {
  if (!epubGlobalPromise) {
    epubGlobalPromise = (async () => {
      installRafShim();
      if (!window.JSZip) await loadScript(jszipUmdUrl);
      if (!window.ePub) await loadScript(epubUmdUrl);
      if (!window.ePub) throw new Error("epubjs UMD 未暴露 window.ePub");
      return window.ePub;
    })();
  }
  return epubGlobalPromise;
}
