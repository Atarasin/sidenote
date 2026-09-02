import type { BookDoc, BookFileMeta, Chapter, TocItem } from "@shared/types/bookdoc";
/**
 * 阅读页：加载书与 BookDoc，组装阅读壳（三区栅格 + 目录拉手）与渲染器。
 * M2：图解演示入口（工具条「🎬 图解」→ 概念面板 → 页边小卡 + 剧场）；
 * M3 将由圈选动线替代演示入口，便签卡复用同一页边挂点。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { getBook, getBookdoc } from "../api";
import DiagramCard from "../diagrams/DiagramCard";
import Theater from "../diagrams/Theater";
import type { DiagramPayload } from "../diagrams/types";
import EpubReader from "./EpubReader";
import type { ReaderHandle } from "./EpubReader";
import PdfReader from "./PdfReader";
import ReaderShell from "./ReaderShell";
import { AnchorRegistry } from "./anchors";

interface Props {
  bookId: string;
}

interface CardSpec {
  key: string;
  paraId: string;
  concept: string;
}

export default function ReaderPage({ bookId }: Props) {
  const [meta, setMeta] = useState<BookFileMeta | null>(null);
  const [doc, setDoc] = useState<BookDoc | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [chapter, setChapter] = useState<Chapter | null>(null);
  const registryRef = useRef(new AnchorRegistry());
  const handleRef = useRef<ReaderHandle | null>(null);

  const [cards, setCards] = useState<CardSpec[]>([]);
  const [theater, setTheater] = useState<DiagramPayload | null>(null);
  const [panelOpen, setPanelOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setMeta(null);
    setDoc(null);
    setError(null);
    setCards([]);
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

  /** 便签/图解的「↗ 原文」：paraId → 所在章节 toc 项跳转（红线 2 引用回跳） */
  const jumpToPara = useCallback(
    (paraId: string) => {
      if (!doc) return;
      const ch = doc.chapters.find((c) => c.paras.some((p) => p.id === paraId));
      if (!ch) return;
      handleRef.current?.jumpTo({
        id: `para-${paraId}`,
        title: ch.title,
        chapterId: ch.id,
        paraId,
      });
    },
    [doc],
  );

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

  const addCard = (paraId: string, concept: string) => {
    setCards((prev) =>
      prev.some((c) => c.paraId === paraId && c.concept === concept)
        ? prev
        : [...prev, { key: `${paraId}:${concept}`, paraId, concept }],
    );
  };

  const marginNotes =
    cards.length > 0
      ? cards.map((c) => (
          <DiagramCard
            key={c.key}
            bookId={bookId}
            paraId={c.paraId}
            concept={c.concept}
            onOpenTheater={setTheater}
            onJumpToPara={jumpToPara}
            onClose={() => setCards((prev) => prev.filter((x) => x.key !== c.key))}
          />
        ))
      : undefined;

  return (
    <>
      <ReaderShell
        title={meta.title}
        chapter={chapter}
        toc={doc.toc}
        onJump={onJump}
        toolbarExtra={
          <button
            type="button"
            className="rounded-lg border border-dashed border-stone-300 px-2 py-1 hover:bg-white"
            title="生成概念图解（M2 演示入口，M3 接圈选动线）"
            onClick={() => setPanelOpen((v) => !v)}
          >
            🎬 图解
          </button>
        }
        marginNotes={marginNotes}
      >
        <Reader
          bookId={bookId}
          doc={doc}
          registry={registryRef.current}
          handleRef={handleRef}
          onChapterChange={setChapter}
        />
      </ReaderShell>

      {panelOpen && (
        <DiagramPanel
          doc={doc}
          currentChapter={chapter}
          onSubmit={(paraId, concept) => {
            addCard(paraId, concept);
            setPanelOpen(false);
          }}
          onClose={() => setPanelOpen(false)}
        />
      )}

      {theater && (
        <Theater
          diagram={theater}
          bookId={bookId}
          onClose={() => setTheater(null)}
          onJumpToPara={jumpToPara}
        />
      )}
    </>
  );
}

/** M2 图解演示面板：选当前章段落 + 输入概念（M3 由圈选替代）。 */
function DiagramPanel({
  doc,
  currentChapter,
  onSubmit,
  onClose,
}: {
  doc: BookDoc;
  currentChapter: Chapter | null;
  onSubmit: (paraId: string, concept: string) => void;
  onClose: () => void;
}) {
  const paras = currentChapter?.paras ?? doc.chapters[0]?.paras ?? [];
  const [paraId, setParaId] = useState(paras[0]?.id ?? "");
  const [concept, setConcept] = useState("");

  // biome-ignore lint/correctness/useExhaustiveDependencies: 章节切换时重置选中段（依赖章节 id 而非 paras 引用）
  useEffect(() => {
    setParaId(paras[0]?.id ?? "");
  }, [currentChapter?.id]);

  return (
    // biome-ignore lint/a11y/useKeyWithClickEvents: 背景点击关闭仅为辅助操作，主要交互在面板控件内
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-stone-900/30 p-4"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="w-96 rounded-xl bg-white p-5 shadow-xl">
        <h3 className="text-sm font-semibold text-stone-800">生成概念图解</h3>
        <p className="mt-1 text-[11px] text-stone-400">
          选择锚定段落并输入概念（M3 起改为书页圈选直接触发）
        </p>
        <label className="mt-4 block text-xs text-stone-600">
          段落
          <select
            className="mt-1 w-full rounded-lg border border-stone-200 px-2 py-1.5 text-xs"
            value={paraId}
            onChange={(e) => setParaId(e.target.value)}
          >
            {paras.map((p) => (
              <option key={p.id} value={p.id}>
                {p.id} · {p.text.slice(0, 24)}…
              </option>
            ))}
          </select>
        </label>
        <label className="mt-3 block text-xs text-stone-600">
          概念
          <input
            className="mt-1 w-full rounded-lg border border-stone-200 px-2 py-1.5 text-xs"
            placeholder="如：供需曲线"
            value={concept}
            onChange={(e) => setConcept(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && concept.trim() && paraId) {
                onSubmit(paraId, concept.trim());
              }
            }}
          />
        </label>
        <div className="mt-4 flex justify-end gap-2 text-xs">
          <button
            type="button"
            className="rounded-lg border border-stone-200 px-3 py-1.5 hover:bg-stone-50"
            onClick={onClose}
          >
            取消
          </button>
          <button
            type="button"
            className="rounded-lg bg-purple-600 px-3 py-1.5 text-white hover:bg-purple-500 disabled:opacity-40"
            disabled={!concept.trim() || !paraId}
            onClick={() => onSubmit(paraId, concept.trim())}
          >
            生成（消耗模型调用）
          </button>
        </div>
      </div>
    </div>
  );
}
