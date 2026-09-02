import type { BookDoc, Chapter, TocItem } from "@shared/types/bookdoc";
import type { Book, Contents, Rendition } from "epubjs";
/**
 * EPUB.js 渲染集成（计划 T0.3.1 / T0.3.3 / T0.3.4）：
 * 章节渲染、翻页（←/→、PgUp/PgDn）、文字可选中（iframe 原生能力）、
 * 渲染 DOM ↔ BookDoc paraId 一一标注、章节/段落跳转。
 */
import { useEffect, useImperativeHandle, useRef, useState } from "react";
import type { RefObject } from "react";
import type { AnchorRegistry } from "./anchors";
import { loadEpubGlobal } from "./epubCompat";
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
  const [renderError, setRenderError] = useState<string | null>(null);

  // biome-ignore lint/correctness/useExhaustiveDependencies: 渲染器生命周期只随书籍实例（bookId）重建
  useEffect(() => {
    const container = viewRef.current;
    if (!container) return;
    setRenderError(null);
    registry.clear();
    chaptersByHref.current = new Map(
      doc.chapters.filter((c) => c.href).map((c) => [basename(c.href as string), c] as const),
    );

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
          el.removeAttribute("data-paraid");
          return;
        }
        const para = chapter.paras[paraIdx];
        el.setAttribute("data-paraid", para.id);
        registry.register(para.id, el, chapter.id);
      });
      // 跳转落点：跨章带 paraId 的跳转在目标章渲染完成后滚到对应段落
      const target = pendingPara.current ? registry.get(pendingPara.current) : undefined;
      if (pendingPara.current && target && target.chapterId === chapter.id) {
        scrollElIntoEpubPage(target.el);
        pendingPara.current = null;
      }
    };

    // epub.js 的 rendered 事件载荷为 (section, view)；文档在 view.contents 上
    const onRendered = (section: unknown, view: unknown) => {
      const href = (section as { href?: string })?.href ?? "";
      const contents = (view as { contents?: Contents } | null)?.contents;
      const chapter = chaptersByHref.current.get(basename(href));
      if (chapter && contents) {
        annotate(contents, chapter);
        onChapterChange?.(chapter);
      }
    };

    let book: Book | null = null;
    let rendition: Rendition | null = null;
    let cancelled = false;
    // epub.js 的 URL 模式会把「去掉文件名后的路径」当作 EPUB 内部路径的基址逐文件请求；
    // 本地服务不暴露 zip 内部结构，因此取回 ArrayBuffer 交给 epub.js 在浏览器内解压。
    void (async () => {
      try {
        const resp = await fetch(`/api/books/${bookId}/source`);
        if (!resp.ok) throw new Error(`源文件请求失败（HTTP ${resp.status}）`);
        const [data, ePub] = await Promise.all([resp.arrayBuffer(), loadEpubGlobal()]);
        if (cancelled) return;
        book = ePub(data);
        rendition = book.renderTo(container, {
          width: "100%",
          height: "100%",
          flow: "paginated",
          spread: "none",
          allowScriptedContent: false,
        });
        renditionRef.current = rendition;
        rendition.on("rendered", onRendered as never);
        // 纸感主题：正文衬线字体栈注入 iframe（UI 文档 §3.1 / §3.8）
        rendition.themes.default({
          "body, p, h1, h2, h3, h4, h5, h6, li, blockquote, pre": {
            "font-family": '"Noto Serif SC", "Songti SC", "SimSun", Georgia, serif',
          },
        });
        // spine 首项常是 nav 目录页；直接打开 BookDoc 第一章
        await rendition.display(doc.chapters[0]?.href ?? undefined);
      } catch (exc) {
        if (!cancelled) {
          setRenderError(`EPUB 渲染失败：${exc instanceof Error ? exc.message : String(exc)}`);
        }
      }
    })();

    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA")) return;
      if (e.key === "ArrowRight" || e.key === "PageDown") void renditionRef.current?.next();
      else if (e.key === "ArrowLeft" || e.key === "PageUp") void renditionRef.current?.prev();
    };
    window.addEventListener("keydown", onKey);

    return () => {
      cancelled = true;
      window.removeEventListener("keydown", onKey);
      renditionRef.current?.destroy();
      renditionRef.current = null;
      void book?.destroy();
      registry.clear();
    };
    // 仅随书籍实例重建（doc/registry 由父组件按 bookId 保证对应）
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

  if (renderError) {
    return (
      <div className="flex h-full items-center justify-center p-8">
        <p className="max-w-md rounded-lg border border-red-200 bg-red-50 p-4 text-xs text-red-600">
          {renderError}
        </p>
      </div>
    );
  }
  return <div ref={viewRef} className="h-full w-full epub-view" />;
}
