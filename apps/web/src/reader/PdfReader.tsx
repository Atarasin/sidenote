import type { BookDoc, Chapter, TocItem } from "@shared/types/bookdoc";
import * as pdfjs from "pdfjs-dist";
import type { PDFDocumentProxy } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
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

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

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

  // 加载文档
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bookId]);

  // 渲染当前页（canvas + 锚点文本层）
  useEffect(() => {
    const pdf = docRef.current;
    const canvas = canvasRef.current;
    const layer = layerRef.current;
    const wrap = wrapRef.current;
    if (!pdf || !canvas || !layer || !wrap || pageNo < 1) return;

    let cancelled = false;
    void (async () => {
      const page = await pdf.getPage(pageNo);
      if (cancelled) return;
      const base = page.getViewport({ scale: 1 });
      const scale = ((wrap.clientWidth - 24) / base.width) * zoom;
      const viewport = page.getViewport({ scale });

      canvas.width = Math.floor(viewport.width);
      canvas.height = Math.floor(viewport.height);
      canvas.style.width = `${Math.floor(viewport.width)}px`;
      canvas.style.height = `${Math.floor(viewport.height)}px`;
      await page.render({ canvasContext: canvas.getContext("2d")!, viewport }).promise;
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

      const place = (
        item: { str: string; transform: number[]; width: number },
        parent: HTMLElement,
      ) => {
        const span = document.createElement("span");
        const tx = pdfjs.Util.transform(viewport.transform, item.transform);
        const fontHeight = Math.hypot(tx[2], tx[3]) || 12;
        span.textContent = item.str;
        span.style.position = "absolute";
        const left = tx[4];
        const top = tx[5] - fontHeight;
        const parentRect = parent === layer ? { left: 0, top: 0 } : parent.dataset;
        const relLeft = left - Number(parentRect.left || 0);
        const relTop = top - Number(parentRect.top || 0);
        span.style.left = `${relLeft}px`;
        span.style.top = `${relTop}px`;
        span.style.fontSize = `${fontHeight}px`;
        span.style.whiteSpace = "pre";
        parent.appendChild(span);
        return { left, top, right: left + item.width * viewport.scale, bottom: top + fontHeight };
      };

      const unionBox = (boxes: { left: number; top: number; right: number; bottom: number }[]) => {
        const left = Math.min(...boxes.map((b) => b.left));
        const top = Math.min(...boxes.map((b) => b.top));
        const right = Math.max(...boxes.map((b) => b.right));
        const bottom = Math.max(...boxes.map((b) => b.bottom));
        return { left, top, right, bottom };
      };

      const groupedItems = new Set<number>();
      for (const [paraIdx, itemIdxs] of groups) {
        const para = paras[paraIdx];
        const box = document.createElement("div");
        box.className = "pdf-para";
        box.dataset.paraId = para.id;
        const boxes = itemIdxs.map((i) => {
          groupedItems.add(i);
          return place(items[i], box);
        });
        const u = unionBox(boxes);
        Object.assign(box.dataset, { left: String(u.left), top: String(u.top) });
        box.style.position = "absolute";
        box.style.left = `${u.left}px`;
        box.style.top = `${u.top}px`;
        box.style.width = `${Math.max(u.right - u.left, 1)}px`;
        box.style.height = `${Math.max(u.bottom - u.top, 1)}px`;
        // 段落盒子本身不参与选区/命中，仅作锚点载体
        box.style.pointerEvents = "none";
        for (const child of [...box.children]) {
          (child as HTMLElement).style.pointerEvents = "auto";
        }
        registry.register(para.id, box, chapter!.id);
        layer.appendChild(box);
      }
      for (let i = 0; i < items.length; i++) {
        if (!groupedItems.has(i)) place(items[i], layer);
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
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
