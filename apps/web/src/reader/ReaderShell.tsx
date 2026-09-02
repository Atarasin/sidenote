import type { Chapter, TocItem } from "@shared/types/bookdoc";
/**
 * 阅读壳（UI 文档 §3.1 / U1）：三区栅格 + 顶部工具条 + 目录拉手 + 窄屏降级。
 * - 顶部工具条 40px：书名 · 当前章节 ｜ 模式开关/费用显示占位（M3/U6 接入）
 * - 中央书页 max-width 46rem 纯白，页面底 #faf9f6
 * - 左右页边便签区各约 15rem（本里程碑留白占位，M3 挂便签）
 * - 视口 <1024px：便签区收起，便签位退化为书页底部堆叠；<768px 不支持
 */
import { useEffect, useState } from "react";

interface Props {
  title: string;
  chapter: Chapter | null;
  toc: TocItem[];
  onJump: (item: TocItem) => void;
  children: React.ReactNode;
}

export default function ReaderShell({ title, chapter, toc, onJump, children }: Props) {
  const [tocOpen, setTocOpen] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA")) return;
      if (e.key === "Escape") setTocOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="flex h-full flex-col bg-[#faf9f6]">
      {/* <768px：不支持 */}
      <UnsupportedNarrow />

      {/* 顶部工具条（40px） */}
      <header className="flex h-10 shrink-0 items-center justify-between gap-3 border-b border-stone-200 bg-white/80 px-4 backdrop-blur">
        <div className="min-w-0 flex-1 truncate text-xs text-stone-500">
          <span className="font-medium text-stone-700">{title}</span>
          <span className="mx-2 text-stone-300">·</span>
          <span>{chapter?.title ?? ""}</span>
        </div>

        {/* 模式开关占位（M3 / U2 接入） */}
        <div
          className="hidden items-center rounded-lg border border-dashed border-stone-300 p-0.5 text-[11px] leading-5 text-stone-400 md:flex"
          title="阅读 / 圈选模式开关将在 M3 接入"
        >
          <span className="rounded-md bg-purple-600 px-2 text-white">阅读</span>
          <span className="px-2">圈选</span>
        </div>

        <div className="flex items-center gap-3 text-[11px] text-stone-400">
          {/* 对话入口占位（M3 / U5） */}
          <span
            className="hidden rounded-lg border border-dashed border-stone-300 px-2 py-1 sm:inline-block"
            title="对话抽屉将在 M3 接入"
          >
            💬 对话
          </span>
          {/* 费用显示占位（M2 / U6 接入） */}
          <span
            className="hidden rounded-lg border border-dashed border-stone-300 px-2 py-1 sm:inline-block"
            title="费用与限流将在 M2 接入"
          >
            ¥0.00 · 本会话
          </span>
          <a href="#/" className="hover:text-stone-600">
            书架
          </a>
        </div>
      </header>

      {/* 三区主体 */}
      <div className="relative flex min-h-0 flex-1">
        {/* 左页边便签区（15rem，占位） */}
        <aside className="hidden w-[15rem] shrink-0 lg:block" aria-hidden />

        {/* 中央书页 */}
        <main className="relative flex min-w-0 flex-1 flex-col">
          <div className="relative mx-auto flex min-h-0 w-full max-w-[46rem] flex-1 flex-col bg-white shadow-[0_1px_8px_rgba(0,0,0,0.06)]">
            <div className="book-page min-h-0 flex-1 overflow-hidden">{children}</div>

            {/* 目录拉手：书页左缘竖排 */}
            <button
              type="button"
              className="absolute top-1/2 left-0 -translate-y-1/2 -translate-x-full items-center rounded-l-lg border border-r-0 border-stone-200 bg-[#faf9f6] px-1.5 py-3 text-xs tracking-widest text-stone-500 hover:bg-stone-100 hover:text-stone-700"
              style={{ writingMode: "vertical-rl" }}
              onClick={() => setTocOpen((v) => !v)}
              onMouseEnter={() => setTocOpen(true)}
              aria-expanded={tocOpen}
            >
              目录 ⟨
            </button>
          </div>

          {/* 窄屏：便签位退化为书页底部堆叠（占位，M3 挂便签） */}
          <div className="mt-3 h-40 shrink-0 overflow-y-auto rounded-lg border border-dashed border-stone-300 bg-white/60 p-3 text-xs text-stone-400 lg:hidden">
            便签区（窄屏底部堆叠 · M3 接入）
          </div>
        </main>

        {/* 右页边便签区（15rem，占位） */}
        <aside className="hidden w-[15rem] shrink-0 lg:block" aria-hidden />

        {/* 目录滑出面板（浮层，不重排书页） */}
        <div
          className={`absolute top-0 bottom-0 left-0 z-30 w-72 border-r border-stone-200 bg-white shadow-xl transition-transform duration-200 ${
            tocOpen ? "translate-x-0" : "-translate-x-full"
          }`}
          onMouseLeave={() => setTocOpen(false)}
        >
          <div className="flex items-center justify-between px-4 py-3 text-xs font-medium text-stone-600">
            目录
            <button
              type="button"
              className="rounded px-1.5 text-stone-400 hover:bg-stone-100 hover:text-stone-600"
              onClick={() => setTocOpen(false)}
              aria-label="关闭目录"
            >
              ✕
            </button>
          </div>
          <nav className="h-[calc(100%-2.75rem)] overflow-y-auto px-2 pb-4">
            <ul className="space-y-0.5">
              {toc.map((item) => (
                <TocNode
                  key={item.id}
                  item={item}
                  depth={0}
                  onJump={(i) => {
                    onJump(i);
                    setTocOpen(false);
                  }}
                />
              ))}
            </ul>
          </nav>
        </div>
      </div>
    </div>
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
        className="block w-full truncate rounded px-2 py-1.5 text-left text-xs text-stone-700 hover:bg-stone-100"
        style={{ paddingLeft: `${8 + depth * 14}px` }}
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

function UnsupportedNarrow() {
  const [narrow, setNarrow] = useState(
    typeof window !== "undefined" ? window.innerWidth < 768 : false,
  );
  useEffect(() => {
    const onResize = () => setNarrow(window.innerWidth < 768);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  if (!narrow) return null;
  return (
    <div className="absolute inset-0 z-50 flex items-center justify-center bg-[#faf9f6]/95 p-8 text-center text-sm text-stone-500">
      视口小于 768px，暂不支持。请放大窗口后阅读（UI 文档 §3.2.5）。
    </div>
  );
}
