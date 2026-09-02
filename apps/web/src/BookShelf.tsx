import type { BookFileMeta } from "@shared/types/bookdoc";
/**
 * 书架入口页（M0）：上传书籍 + 打开已解析的书（#/read/<bookId>）。
 * 有书在解析中时轮询刷新，直到全部到达终态。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { listBooks, uploadBook } from "./api";
import { formatBytes, parseStatusLabel } from "./lib/format";

export default function BookShelf() {
  const [books, setBooks] = useState<BookFileMeta[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      setBooks(await listBooks());
    } catch (e) {
      setError(`获取书籍列表失败：${e instanceof Error ? e.message : String(e)}`);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // 解析中的书：轮询直到终态（大书解析需要时间，「打开」按钮依赖状态更新）
  const hasPending = books.some((b) => b.parseStatus === "pending" || b.parseStatus === "parsing");
  useEffect(() => {
    if (!hasPending) return;
    const timer = window.setInterval(() => void refresh(), 1200);
    return () => window.clearInterval(timer);
  }, [hasPending, refresh]);

  const onUpload = async (file: File) => {
    setUploading(true);
    setError(null);
    try {
      await uploadBook(file);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  return (
    <main className="mx-auto max-w-3xl px-6 py-16">
      <h1 className="text-3xl font-bold tracking-tight">sidenote</h1>
      <p className="mt-2 text-sm text-gray-600">
        Agent 辅助阅读器 · 上传 EPUB / 文字版 PDF 开始阅读（书籍只存本地）
      </p>

      <section className="mt-10 rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
        <div className="flex items-center gap-4">
          <input
            ref={fileInput}
            type="file"
            accept=".epub,.pdf"
            disabled={uploading}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) onUpload(file);
            }}
            className="text-sm"
          />
          {uploading && <span className="text-sm text-gray-500">上传中…</span>}
        </div>
        {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
      </section>

      <section className="mt-8">
        <h2 className="mb-3 text-sm font-semibold text-gray-700">我的书（按上传时间）</h2>
        {books.length === 0 ? (
          <p className="text-sm text-gray-400">还没有书，先上传一本吧。</p>
        ) : (
          <ul className="divide-y divide-gray-100 rounded-xl border border-gray-200 bg-white">
            {books.map((b) => (
              <li key={b.bookId} className="flex items-center gap-4 px-5 py-3">
                <span className="w-12 text-xs text-gray-400 uppercase">{b.format}</span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{b.title}</p>
                  <p className="text-xs text-gray-400">
                    {formatBytes(b.sizeBytes)} · {b.chaptersCount} 章 · {b.parasCount} 段
                    {b.parseError ? ` · ${b.parseError}` : ""}
                  </p>
                </div>
                <span
                  className={
                    b.parseStatus === "success"
                      ? "text-xs text-emerald-600"
                      : "text-xs text-gray-400"
                  }
                >
                  {parseStatusLabel(b.parseStatus)}
                </span>
                {b.parseStatus === "success" && (
                  <a
                    href={`#/read/${b.bookId}`}
                    className="rounded-md bg-purple-600 px-3 py-1 text-xs text-white hover:bg-purple-500"
                  >
                    打开
                  </a>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
