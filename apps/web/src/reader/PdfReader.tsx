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
import { groupItemsByParas } from "./textAlign";

// workerPort 直接持有 worker 实例，绕开 module-worker 兼容性问题
pdfjs.GlobalWorkerOptions.workerPort = new PdfjsWorker();

interface Props {
  bookId: string;
  doc: BookDoc;
  registry: AnchorRegistry;
  handleRef: RefObject<ReaderHandle | null>;
  onChapterChange?: (chapter: Chapter | null) => void;
}

export default function PdfReader({ bookId, doc, registry, handleRef, onChapterChange }: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const layerRef = useRef<HTMLDivElement>(null);
  const docRef = useRef<PDFDocumentProxy | null>(null);
  const pendingPara = useRef<string | null>(null);
  const [numPages, setNumPages] = useState(0);
  const [pageNo, setPageNo] = useState(1);
  const [zoom, setZoom] = useState(1);
  const [renderError, setRenderError] = useState<string | null>(null);

  // 加载文档
  // biome-ignore lint/correctness/useExhaustiveDependencies: 文档加载只随书籍实例重建
  useEffect(() => {
    registry.clear();
    const task = pdfjs.getDocument(`/api/books/${bookId}/source`);
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
        layer.style.position = "relative";
        layer.style.width = `${canvas.width}px`;
        layer.style.height = `${canvas.height}px`;

        const paras = chapter?.paras ?? [];
        const { groups } = groupItemsByParas(
          items,
          paras.map((p) => p.text),
        );

        // 先量测（绝对页坐标），再创建段落盒，最后按段落盒原点相对放置 span。
        // 顺序不可颠倒：span 必须拿到已定位的段落盒原点，否则选中层会整体偏移。
        const measure = (item: { str: string; transform: number[]; width: number }) => {
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
          const span = document.createElement("span");
          span.textContent = item.str;
          span.style.position = "absolute";
          span.style.left = `${g.left - origin.left}px`;
          span.style.top = `${g.top - origin.top}px`;
          span.style.fontSize = `${g.fontHeight}px`;
          span.style.whiteSpace = "pre";
          span.style.pointerEvents = "auto";
          box.appendChild(span);
          return g;
        };

        const unionBox = (
          boxes: { left: number; top: number; right: number; bottom: number }[],
        ) => {
          const left = Math.min(...boxes.map((b) => b.left));
          const top = Math.min(...boxes.map((b) => b.top));
          const right = Math.max(...boxes.map((b) => b.right));
          const bottom = Math.max(...boxes.map((b) => b.bottom));
          return { left, top, right, bottom };
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
          itemIdxs.forEach((i, k) => place(items[i], box, geometries[k]));
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
        setPageNo((n) => Math.min(n + 1, numPages));
      else if (e.key === "ArrowLeft" || e.key === "PageUp") setPageNo((n) => Math.max(n - 1, 1));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [numPages]);

  useImperativeHandle(handleRef, () => ({
    jumpTo(toc: TocItem) {
      const paraById = (id?: string) =>
        id ? doc.chapters.flatMap((c) => c.paras).find((p) => p.id === id) : undefined;
      const target =
        paraById(toc.paraId) ??
        doc.chapters.find((c) => c.id === toc.chapterId)?.paras.find((p) => p.page != null);
      if (target?.page == null) return;
      const next = Math.min(Math.max(target.page + 1, 1), numPages || 1);
      if (next === pageNo) {
        // 同页跳转：直接滚动定位（渲染 effect 不会重跑）
        const anchored = registry.get(target.id);
        if (anchored) {
          anchored.el.scrollIntoView({ block: "center" });
          anchored.el.classList.add("anchor-flash");
          window.setTimeout(() => anchored.el.classList.remove("anchor-flash"), 2000);
        }
        return;
      }
      pendingPara.current = toc.paraId ?? target.id;
      setPageNo(next);
    },
    next() {
      setPageNo((n) => Math.min(n + 1, numPages));
    },
    prev() {
      setPageNo((n) => Math.max(n - 1, 1));
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
    <div className="pdf-view flex h-full w-full flex-col items-center overflow-auto" ref={wrapRef}>
      <div className="relative" style={{ margin: "12px 0" }}>
        <canvas ref={canvasRef} className="block bg-white shadow-sm" />
        <div ref={layerRef} className="pdf-text-layer absolute inset-0" />
      </div>
      {numPages > 0 && (
        <div className="pb-4 text-xs text-gray-400">
          {pageNo} / {numPages}
          <button
            type="button"
            className="ml-3 rounded border border-gray-200 px-2 hover:bg-gray-50"
            onClick={() => setZoom((z) => Math.max(0.5, z - 0.15))}
          >
            −
          </button>
          <button
            type="button"
            className="ml-1 rounded border border-gray-200 px-2 hover:bg-gray-50"
            onClick={() => setZoom((z) => Math.min(3, z + 0.15))}
          >
            +
          </button>
        </div>
      )}
    </div>
  );
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
