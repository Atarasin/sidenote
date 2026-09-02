import type { BookDoc, BookFileMeta, Chapter, TocItem } from "@shared/types/bookdoc";
/**
 * 阅读页（M0 Slice 0.3 基础形态）：加载书与 BookDoc，目录列表 + 渲染器。
 * Slice 0.4 在此之上叠加正式阅读壳（三区栅格、纸感主题、目录拉手、窄屏降级）。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { getBook, getBookdoc } from "../api";
import EpubReader from "./EpubReader";
import type { ReaderHandle } from "./EpubReader";
import PdfReader from "./PdfReader";
import { AnchorRegistry } from "./anchors";

interface Props {
  bookId: string;
}

export default function ReaderPage({ bookId }: Props) {
  const [meta, setMeta] = useState<BookFileMeta | null>(null);
  const [doc, setDoc] = useState<BookDoc | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [chapter, setChapter] = useState<Chapter | null>(null);
  const [tocOpen, setTocOpen] = useState(true);
  const registryRef = useRef(new AnchorRegistry());
  const handleRef = useRef<ReaderHandle | null>(null);

  useEffect(() => {
    let cancelled = false;
    setMeta(null);
    setDoc(null);
    setError(null);
    Promise.all([getBook(bookId), getBookdoc(bookId)])
      .then(([m, d]) => {
        if (cancelled) return;
        setMeta(m);
        setDoc(d);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [bookId]);

  const onJump = useCallback((item: TocItem) => {
    handleRef.current?.jumpTo(item);
  }, []);

  if (error) {
    return (
      <main className="mx-auto max-w-3xl px-6 py-16">
        <p className="text-sm text-red-600">无法打开这本书：{error}</p>
        <a href="#/" className="mt-3 inline-block text-sm text-purple-600 hover:underline">
          ← 返回书架
        </a>
      </main>
    );
  }
  if (!meta || !doc) {
    return (
      <main className="mx-auto max-w-3xl px-6 py-16">
        <p className="text-sm text-gray-400">加载中…</p>
      </main>
    );
  }

  const Reader = meta.format === "epub" ? EpubReader : PdfReader;

  return (
    <div className="flex h-full">
      <aside
        className={`${tocOpen ? "w-64" : "w-10"} shrink-0 border-r border-gray-200 bg-white transition-all`}
      >
        <button
          type="button"
          className="w-full px-3 py-2 text-left text-xs text-gray-500 hover:bg-gray-50"
          onClick={() => setTocOpen((v) => !v)}
        >
          {tocOpen ? "◀ 收起目录" : "▶"}
        </button>
        {tocOpen && <TocTree toc={doc.toc} onJump={onJump} />}
      </aside>
      <section className="min-w-0 flex-1 bg-[#faf9f6]">
        <header className="flex h-10 items-center justify-between border-b border-gray-200 bg-white px-4">
          <span className="truncate text-xs text-gray-500">
            {meta.title} · {chapter?.title ?? ""}
          </span>
          <a href="#/" className="text-xs text-gray-400 hover:text-gray-600">
            书架
          </a>
        </header>
        <div className="h-[calc(100%-2.5rem)] px-6 py-4">
          <Reader
            bookId={bookId}
            doc={doc}
            registry={registryRef.current}
            handleRef={handleRef}
            onChapterChange={setChapter}
          />
        </div>
      </section>
    </div>
  );
}

function TocTree({ toc, onJump }: { toc: TocItem[]; onJump: (item: TocItem) => void }) {
  return (
    <nav className="h-[calc(100%-2rem)] overflow-auto px-2 py-2">
      <ul className="space-y-0.5">
        {toc.map((item) => (
          <TocNode key={item.id} item={item} depth={0} onJump={onJump} />
        ))}
      </ul>
    </nav>
  );
}

function TocNode({
  item,
  depth,
  onJump,
}: {
  item: TocItem;
  depth: number;
  onJump: (item: TocItem) => void;
}) {
  return (
    <li>
      <button
        type="button"
        className="block w-full truncate rounded px-2 py-1 text-left text-xs text-gray-700 hover:bg-gray-100"
        style={{ paddingLeft: `${8 + depth * 12}px` }}
        onClick={() => onJump(item)}
      >
        {item.title}
      </button>
      {item.children?.map((child) => (
        <ul key={child.id} className="space-y-0.5">
          <TocNode item={child} depth={depth + 1} onJump={onJump} />
        </ul>
      ))}
    </li>
  );
}
