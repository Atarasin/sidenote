import type { BookDoc, BookFileMeta, Chapter, TocItem } from "@shared/types/bookdoc";
/**
 * 阅读页：加载书与 BookDoc，组装阅读壳（三区栅格 + 目录拉手）与渲染器。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { getBook, getBookdoc } from "../api";
import EpubReader from "./EpubReader";
import type { ReaderHandle } from "./EpubReader";
import PdfReader from "./PdfReader";
import ReaderShell from "./ReaderShell";
import { AnchorRegistry } from "./anchors";

interface Props {
  bookId: string;
}

export default function ReaderPage({ bookId }: Props) {
  const [meta, setMeta] = useState<BookFileMeta | null>(null);
  const [doc, setDoc] = useState<BookDoc | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [chapter, setChapter] = useState<Chapter | null>(null);
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
        <p className="text-sm text-stone-400">加载中…</p>
      </main>
    );
  }

  const Reader = meta.format === "epub" ? EpubReader : PdfReader;

  return (
    <ReaderShell title={meta.title} chapter={chapter} toc={doc.toc} onJump={onJump}>
      <Reader
        bookId={bookId}
        doc={doc}
        registry={registryRef.current}
        handleRef={handleRef}
        onChapterChange={setChapter}
      />
    </ReaderShell>
  );
}
