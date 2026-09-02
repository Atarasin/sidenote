import type { BookDoc, Chapter, TocItem } from "@shared/types/bookdoc";
import ePub from "epubjs";
import type { Book, Contents, Rendition } from "epubjs";
/**
 * EPUB.js 渲染集成（计划 T0.3.1 / T0.3.3 / T0.3.4）：
 * 章节渲染、翻页（←/→、PgUp/PgDn）、文字可选中（iframe 原生能力）、
 * 渲染 DOM ↔ BookDoc paraId 一一标注、章节/段落跳转。
 */
import { useEffect, useImperativeHandle, useRef } from "react";
import type { RefObject } from "react";
import type { AnchorRegistry } from "./anchors";
import { alignBlocksToParas } from "./textAlign";

export const BLOCK_SELECTOR = "p,h1,h2,h3,h4,h5,h6,li,blockquote,pre,table";

export interface ReaderHandle {
  jumpTo(toc: TocItem): void;
  next(): void;
  prev(): void;
}

interface Props {
  bookId: string;
  doc: BookDoc;
  registry: AnchorRegistry;
  handleRef: RefObject<ReaderHandle | null>;
  onChapterChange?: (chapter: Chapter | null) => void;
}

function basename(href: string): string {
  return href.split(/[?#]/)[0].split("/").pop() ?? href;
}

/** epub.js 分栏布局：按元素所在栏翻页（scrollLeft 对齐到栏宽整数倍）。 */
function scrollElIntoEpubPage(el: HTMLElement): void {
  const win = el.ownerDocument.defaultView;
  const docEl = el.ownerDocument.documentElement;
  if (!win) return;
  const pageWidth = win.innerWidth || docEl.clientWidth || 1;
  const x = el.getBoundingClientRect().left + win.scrollX;
  docEl.scrollLeft = Math.max(0, Math.floor(x / pageWidth) * pageWidth);
}

export default function EpubReader({ bookId, doc, registry, handleRef, onChapterChange }: Props) {
  const viewRef = useRef<HTMLDivElement>(null);
  const renditionRef = useRef<Rendition | null>(null);
  const pendingPara = useRef<string | null>(null);
  const chaptersByHref = useRef(new Map<string, Chapter>());

  useEffect(() => {
    const container = viewRef.current;
    if (!container) return;
    registry.clear();
    chaptersByHref.current = new Map(
      doc.chapters.filter((c) => c.href).map((c) => [basename(c.href as string), c] as const),
    );

    const book: Book = ePub(`/api/books/${bookId}/source`);
    const rendition = book.renderTo(container, {
      width: "100%",
      height: "100%",
      flow: "paginated",
      spread: "none",
      allowScriptedContent: false,
    });
    renditionRef.current = rendition;
    void rendition.display();

    const annotate = (contents: Contents, chapter: Chapter) => {
      const body = contents.document.body;
      if (!body) return;
      const blocks = [...body.querySelectorAll(BLOCK_SELECTOR)] as HTMLElement[];
      const topBlocks = blocks.filter((el) => !el.parentElement?.closest(BLOCK_SELECTOR));
      const assignments = alignBlocksToParas(
        topBlocks.map((el) => el.textContent ?? ""),
        chapter.paras.map((p) => p.text),
      );
      registry.clearChapter(chapter.id);
      topBlocks.forEach((el, i) => {
        const paraIdx = assignments[i];
        if (paraIdx == null) {
          delete el.dataset.paraId;
          return;
        }
        const para = chapter.paras[paraIdx];
        el.dataset.paraId = para.id;
        registry.register(para.id, el, chapter.id);
      });
      // 跳转落点：本章渲染完成后滚到目标段落
      if (pendingPara.current && registry.get(pendingPara.current)?.chapterId === chapter.id) {
        const anchored = registry.get(pendingPara.current);
        if (anchored) scrollElIntoEpubPage(anchored.el);
        pendingPara.current = null;
      }
    };

    const onRendered = (section: unknown, contents: Contents) => {
      const href = (section as { href?: string })?.href ?? "";
      const chapter = chaptersByHref.current.get(basename(href));
      if (chapter) {
        annotate(contents, chapter);
        onChapterChange?.(chapter);
      }
    };
    rendition.on("rendered", onRendered as never);

    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA")) return;
      if (e.key === "ArrowRight" || e.key === "PageDown") void rendition.next();
      else if (e.key === "ArrowLeft" || e.key === "PageUp") void rendition.prev();
    };
    window.addEventListener("keydown", onKey);

    return () => {
      window.removeEventListener("keydown", onKey);
      rendition.destroy();
      void book.destroy();
      registry.clear();
      renditionRef.current = null;
    };
    // 仅随书籍实例重建（doc/registry 由父组件按 bookId 保证对应）
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bookId]);

  useImperativeHandle(handleRef, () => ({
    jumpTo(toc: TocItem) {
      const chapter = doc.chapters.find((c) => c.id === toc.chapterId);
      if (!chapter?.href) return;
      const anchored = toc.paraId ? registry.get(toc.paraId) : undefined;
      if (anchored && anchored.chapterId === chapter.id) {
        scrollElIntoEpubPage(anchored.el);
        return;
      }
      pendingPara.current = toc.paraId ?? null;
      void renditionRef.current?.display(chapter.href);
    },
    next() {
      void renditionRef.current?.next();
    },
    prev() {
      void renditionRef.current?.prev();
    },
  }));

  return <div ref={viewRef} className="h-full w-full epub-view" />;
}
