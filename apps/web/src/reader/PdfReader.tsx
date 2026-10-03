import type { BookDoc, Chapter, TocItem } from "@shared/types/bookdoc";
import * as pdfjs from "pdfjs-dist";
import type { PDFDocumentProxy } from "pdfjs-dist";
import PdfjsWorker from "pdfjs-dist/build/pdf.worker.min.mjs?worker";
/**
 * PDF.js 渲染集成（计划 T0.3.2 / T0.3.3 / T0.3.4）：
 * 文字版 PDF 单页渲染（canvas + 自建文本层）、翻页、文字可选中、
 * 文本层 item ↔ BookDoc paraId 分组标注、按页/按段落跳转。
 */
import { useEffect, useImperativeHandle, useRef, useState } from "react";
import type { RefObject } from "react";
import type { ReaderHandle } from "./EpubReader";
import type { AnchorRegistry } from "./anchors";
import { type ItemGeometry, spanOffset, unionBox } from "./pdfLayout";
import { groupItemsByParas } from "./textAlign";
import { resolveTocTarget } from "./tocTarget";

// workerPort 直接持有 worker 实例，绕开 module-worker 兼容性问题
pdfjs.GlobalWorkerOptions.workerPort = new PdfjsWorker();

interface Props {
  bookId: string;
  doc: BookDoc;
  registry: AnchorRegistry;
  handleRef: RefObject<ReaderHandle | null>;
  onChapterChange?: (chapter: Chapter | null) => void;
  /** 滚动/翻页/缩放后触发（M3 便签重定位，T3.3.1） */
  onLayoutChange?: () => void;
  /**
   * 书页滚动容器（wrapRef）的对开引用：涂写层覆盖在不滚动的 .book-page 上，
   * 锚定内容的笔迹需要感知这里的滚动偏移与滚动事件（缺陷 16）。
   */
  scrollHostRef?: RefObject<HTMLDivElement | null>;
}

export default function PdfReader({
  bookId,
  doc,
  registry,
  handleRef,
  onChapterChange,
  onLayoutChange,
  scrollHostRef,
}: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const layerRef = useRef<HTMLDivElement>(null);
  const docRef = useRef<PDFDocumentProxy | null>(null);
  const pendingPara = useRef<string | null>(null);
  const [numPages, setNumPages] = useState(0);
  const [pageNo, setPageNo] = useState(1);
  const [pageInput, setPageInput] = useState("1");
  const [zoom, setZoom] = useState(1);
  const [renderError, setRenderError] = useState<string | null>(null);

  // 页码输入框跟随实际页码（翻页/快捷键/跳转都同步）
  useEffect(() => setPageInput(String(pageNo)), [pageNo]);

  const commitPageInput = () => {
    const parsed = Number.parseInt(pageInput, 10);
    if (!Number.isFinite(parsed)) {
      setPageInput(String(pageNo));
      return;
    }
    const next = clampPage(parsed, numPages);
    setPageInput(String(next));
    setPageNo(next);
  };

  // 加载文档
  // biome-ignore lint/correctness/useExhaustiveDependencies: 文档加载只随书籍实例重建
  useEffect(() => {
    registry.clear();
    // cmaps/standard_fonts 由 vite-plugin-static-copy 提供在 /pdfjs/ 下；
    // 缺失时 CJK 非嵌入字体 PDF 在浏览器端没有文本层（无锚点、无选中）
    const task = pdfjs.getDocument({
      url: `/api/books/${bookId}/source`,
      cMapUrl: "/pdfjs/cmaps/",
      cMapPacked: true,
      standardFontDataUrl: "/pdfjs/standard_fonts/",
    });
    let cancelled = false;
    task.promise
      .then((pdf) => {
        if (cancelled) {
          void pdf.destroy();
          return;
        }
        docRef.current = pdf;
        setNumPages(pdf.numPages);
        setPageNo(1);
      })
      .catch(() => setNumPages(0));
    return () => {
      cancelled = true;
      docRef.current?.destroy();
      docRef.current = null;
    };
  }, [bookId]);

  // 渲染当前页（canvas + 锚点文本层）
  // biome-ignore lint/correctness/useExhaustiveDependencies: 页渲染随页码/缩放/文档重建
  useEffect(() => {
    const pdf = docRef.current;
    const canvas = canvasRef.current;
    const layer = layerRef.current;
    const wrap = wrapRef.current;
    if (!pdf || !canvas || !layer || !wrap || pageNo < 1) return;

    let cancelled = false;
    let renderTask: { cancel(): void } | null = null;
    void (async () => {
      try {
        const page = await pdf.getPage(pageNo);
        if (cancelled) return;
        const base = page.getViewport({ scale: 1 });
        const scale = ((wrap.clientWidth - 24) / base.width) * zoom;
        const viewport = page.getViewport({ scale });

        canvas.width = Math.floor(viewport.width);
        canvas.height = Math.floor(viewport.height);
        canvas.style.width = `${Math.floor(viewport.width)}px`;
        canvas.style.height = `${Math.floor(viewport.height)}px`;
        const ctx = canvas.getContext("2d");
        if (!ctx) throw new Error("无法获取 canvas 2d 上下文");
        const task = page.render({ canvasContext: ctx, viewport });
        renderTask = task;
        await task.promise;
        if (cancelled) return;

        const content = await page.getTextContent();
        if (cancelled) return;

        // 本章内、出现在本页的段落（含从上一页延续的段落：靠 indexOf 对齐天然跳过其页首尾巴）
        const chapter = chapterForPage(doc, pageNo - 1);
        const items = content.items as { str: string; transform: number[]; width: number }[];
        layer.replaceChildren();
        // 文本层保持绝对定位覆盖 canvas（类名 absolute inset-0）；写成 relative 会多占一份高度

        const paras = chapter?.paras ?? [];
        const { groups } = groupItemsByParas(
          items,
          paras.map((p) => p.text),
        );

        // 先量测（绝对页坐标），再创建段落盒，最后按段落盒原点相对放置 span。
        // 顺序不可颠倒：span 必须拿到已定位的段落盒原点，否则选中层会整体偏移。
        const measure = (item: {
          str: string;
          transform: number[];
          width: number;
        }): ItemGeometry => {
          const tx = pdfjs.Util.transform(viewport.transform, item.transform);
          const fontHeight = Math.hypot(tx[2], tx[3]) || 12;
          const left = tx[4];
          const top = tx[5] - fontHeight;
          return {
            left,
            top,
            right: left + item.width * viewport.scale,
            bottom: top + fontHeight,
            fontHeight,
          };
        };

        const place = (
          item: { str: string; transform: number[]; width: number },
          box: HTMLElement,
          origin: { left: number; top: number },
        ) => {
          const g = measure(item);
          const off = spanOffset(g, origin);
          const span = document.createElement("span");
          span.textContent = item.str;
          span.style.position = "absolute";
          span.style.left = `${off.left}px`;
          span.style.top = `${off.top}px`;
          span.style.fontSize = `${g.fontHeight}px`;
          span.style.whiteSpace = "pre";
          span.style.pointerEvents = "auto";
          box.appendChild(span);
          return g;
        };

        const groupedItems = new Set<number>();
        for (const [paraIdx, itemIdxs] of groups) {
          const para = paras[paraIdx];
          const geometries = itemIdxs.map((i) => {
            groupedItems.add(i);
            return measure(items[i]);
          });
          const u = unionBox(geometries);
          const box = document.createElement("div");
          box.className = "pdf-para";
          box.setAttribute("data-paraid", para.id);
          box.style.position = "absolute";
          box.style.left = `${u.left}px`;
          box.style.top = `${u.top}px`;
          box.style.width = `${Math.max(u.right - u.left, 1)}px`;
          box.style.height = `${Math.max(u.bottom - u.top, 1)}px`;
          // 段落盒本身不参与选区/命中，仅作锚点载体；span 负责选中
          box.style.pointerEvents = "none";
          for (const i of itemIdxs) place(items[i], box, u);
          if (chapter) registry.register(para.id, box, chapter.id);
          layer.appendChild(box);
        }
        for (let i = 0; i < items.length; i++) {
          if (!groupedItems.has(i)) place(items[i], layer, { left: 0, top: 0 });
        }

        if (chapter) onChapterChange?.(chapter);
        if (pendingPara.current) {
          const anchored = registry.get(pendingPara.current);
          if (anchored && anchored.chapterId === chapter?.id) {
            anchored.el.scrollIntoView({ block: "center" });
            anchored.el.classList.add("anchor-flash");
            window.setTimeout(() => anchored.el.classList.remove("anchor-flash"), 2000);
          }
          pendingPara.current = null;
        }
        onLayoutChange?.();
      } catch (exc) {
        if (!cancelled) {
          setRenderError(`PDF 渲染失败：${exc instanceof Error ? exc.message : String(exc)}`);
        }
      }
    })();
    return () => {
      cancelled = true;
      // StrictMode 双跑 / 快速翻页时取消在途渲染，避免同一 canvas 上挂死
      try {
        renderTask?.cancel();
      } catch {
        /* 任务已结束 */
      }
    };
  }, [bookId, pageNo, zoom, numPages]);

  // 翻页快捷键
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA")) return;
      if (e.key === "ArrowRight" || e.key === "PageDown")
        setPageNo((n) => clampPage(n + 1, numPages));
      else if (e.key === "ArrowLeft" || e.key === "PageUp")
        setPageNo((n) => clampPage(n - 1, numPages));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [numPages]);

  // 滚动（含缩放后回流）→ 便签重定位
  // biome-ignore lint/correctness/useExhaustiveDependencies: 只随挂载绑定一次，回调由父组件保持稳定
  useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap) return;
    const onScroll = () => onLayoutChange?.();
    wrap.addEventListener("scroll", onScroll, { passive: true });
    return () => wrap.removeEventListener("scroll", onScroll);
  }, []);

  useImperativeHandle(handleRef, () => ({
    jumpTo(toc: TocItem): boolean {
      const target = resolveTocTarget(doc, toc);
      // 目标章节不存在（解析器已丢弃）或文档尚未就绪：返回 false，由 ReaderPage 提示，
      // 不允许静默什么都不做（M0 缺陷 #14）
      if (!target || numPages < 1) return false;
      const next = clampPage(target.page + 1, numPages);
      if (next === pageNo) {
        // 同页跳转：直接滚动定位（渲染 effect 不会重跑）
        const anchored = registry.get(target.paraId);
        if (anchored) {
          anchored.el.scrollIntoView({ block: "center" });
          anchored.el.classList.add("anchor-flash");
          window.setTimeout(() => anchored.el.classList.remove("anchor-flash"), 2000);
        }
        return true;
      }
      pendingPara.current = target.paraId;
      setPageNo(next);
      return true;
    },
    next() {
      setPageNo((n) => clampPage(n + 1, numPages));
    },
    prev() {
      setPageNo((n) => clampPage(n - 1, numPages));
    },
  }));

  if (renderError) {
    return (
      <div className="flex h-full items-center justify-center p-8">
        <p className="max-w-md rounded-lg border border-red-200 bg-red-50 p-4 text-xs text-red-600">
          {renderError}
        </p>
      </div>
    );
  }
  return (
    <div className="pdf-view flex h-full w-full flex-col overflow-hidden">
      {/* 滚动容器：缩放基准宽取这里（clientWidth 已扣除滚动条）；偏移同时暴露给涂写层 */}
      <div
        ref={(el) => {
          wrapRef.current = el;
          if (scrollHostRef) scrollHostRef.current = el;
        }}
        className="flex min-h-0 w-full flex-1 flex-col items-center overflow-auto"
      >
        <div className="relative" style={{ margin: "12px 0" }}>
          <canvas ref={canvasRef} className="block bg-white shadow-sm" />
          <div ref={layerRef} className="pdf-text-layer absolute inset-0" />
        </div>
      </div>
      {numPages > 0 && (
        <footer className="flex shrink-0 flex-wrap items-center justify-center gap-2 border-t border-stone-200 bg-white/85 px-3 py-1.5 text-xs text-stone-500">
          <button
            type="button"
            className="rounded border border-stone-200 px-2 py-0.5 hover:bg-stone-100 disabled:cursor-not-allowed disabled:opacity-40"
            onClick={() => setPageNo((n) => clampPage(n - 1, numPages))}
            disabled={pageNo <= 1}
            title="上一页（← / PageUp）"
          >
            ‹ 上一页
          </button>
          <span className="flex items-center gap-1 tabular-nums">
            <input
              className="w-10 rounded border border-stone-200 px-1 py-0.5 text-center tabular-nums"
              value={pageInput}
              onChange={(e) => setPageInput(e.target.value)}
              onBlur={commitPageInput}
              onKeyDown={(e) => {
                if (e.key === "Enter") e.currentTarget.blur();
              }}
              aria-label="跳转到页码"
            />
            / {numPages}
          </span>
          <button
            type="button"
            className="rounded border border-stone-200 px-2 py-0.5 hover:bg-stone-100 disabled:cursor-not-allowed disabled:opacity-40"
            onClick={() => setPageNo((n) => clampPage(n + 1, numPages))}
            disabled={pageNo >= numPages}
            title="下一页（→ / PageDown）"
          >
            下一页 ›
          </button>
          <span className="mx-1 h-3 w-px bg-stone-200" />
          <button
            type="button"
            className="rounded border border-stone-200 px-2 py-0.5 hover:bg-stone-100"
            onClick={() => setZoom((z) => Math.max(0.5, z - 0.15))}
            title="缩小"
          >
            −
          </button>
          <button
            type="button"
            className="rounded border border-stone-200 px-2 py-0.5 hover:bg-stone-100"
            onClick={() => setZoom((z) => Math.min(3, z + 0.15))}
            title="放大"
          >
            +
          </button>
          <span className="ml-1 hidden text-stone-400 sm:inline">← → 翻页</span>
        </footer>
      )}
    </div>
  );
}

/** 页码夹取：文档未就绪（numPages=0）时也不得把页码推成 0（渲染 effect 会直接跳过）。 */
function clampPage(page: number, numPages: number): number {
  return Math.min(Math.max(page, 1), Math.max(numPages, 1));
}

function chapterForPage(doc: BookDoc, page0: number): Chapter | null {
  let current: Chapter | null = null;
  for (const ch of doc.chapters) {
    const first = ch.paras.find((p) => p.page != null)?.page;
    if (first != null && first <= page0) current = ch;
    else if (first != null && first > page0) break;
  }
  return current ?? doc.chapters[0] ?? null;
}
