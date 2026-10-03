import type { BookDoc, BookFileMeta, Chapter, TocItem } from "@shared/types/bookdoc";
/**
 * 阅读页：加载书与 BookDoc，组装阅读壳与渲染器。
 * M3：涂写动线（圈选 → 意图解析 → 讲解便签/图解卡）、对话抽屉、费用呈现。
 * 快捷键 A（圈选）/ D（对话）/ Esc（逐层关闭）在输入框聚焦时一律失效（UI §3.7）。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  type Citation,
  askQuestion,
  getBook,
  getBookdoc,
  getSessionId,
  parseScribbleIntent,
} from "../api";
import BookMap from "../chat/BookMap";
import ChatDrawer, { type DrawerMessage } from "../chat/ChatDrawer";
import DiagramCard from "../diagrams/DiagramCard";
import Theater from "../diagrams/Theater";
import type { DiagramPayload } from "../diagrams/types";
import ScribbleLayer, { type ScribbleSubmit } from "../scribbles/ScribbleLayer";
import { composeRegionImage } from "../scribbles/composeImage";
import { paraScore, selectionRect } from "../scribbles/geometry";
import StickyBoard, { type StickySlot } from "../sticky/StickyBoard";
import StickyCard, { type StickyAnswer } from "../sticky/StickyCard";
import CostBadge, { useUsageSummary } from "../usage/CostBadge";
import EpubReader from "./EpubReader";
import type { ReaderHandle } from "./EpubReader";
import PdfReader from "./PdfReader";
import ReaderShell from "./ReaderShell";
import { AnchorRegistry } from "./anchors";
import { hostLocalRect } from "./hostRect";

interface Props {
  bookId: string;
}

/** 1×1 白图：截图合成失败时的占位（意图解析接口要求非空 image）。 */
const BLANK_PNG =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/x8AAwMCAO+ip9sAAAAASUVORK5CYII=";

type Mode = "reading" | "annotating";

interface CardSpec {
  key: string;
  paraId: string;
  concept: string;
}

interface StickySpec {
  key: string;
  paraId: string;
  question: string;
  state: "pending" | "answered" | "failed";
  result?: StickyAnswer;
  failNote?: string;
  thumb?: string;
}

export default function ReaderPage({ bookId }: Props) {
  const [meta, setMeta] = useState<BookFileMeta | null>(null);
  const [doc, setDoc] = useState<BookDoc | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [chapter, setChapter] = useState<Chapter | null>(null);
  const registryRef = useRef(new AnchorRegistry());
  const handleRef = useRef<ReaderHandle | null>(null);
  const pageRef = useRef<HTMLDivElement | null>(null);

  // M3 状态
  const [mode, setMode] = useState<Mode>("reading");
  const [layoutTick, setLayoutTick] = useState(0);
  const [clearToken, setClearToken] = useState(0);
  const [cards, setCards] = useState<CardSpec[]>([]);
  const [stickies, setStickies] = useState<StickySpec[]>([]);
  const [theater, setTheater] = useState<DiagramPayload | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerMsgs, setDrawerMsgs] = useState<DrawerMessage[]>([]);
  const [drawerBusy, setDrawerBusy] = useState(false);
  const [drawerHint, setDrawerHint] = useState("本章");
  const [mapOpen, setMapOpen] = useState(false);
  const [jumpHint, setJumpHint] = useState<string | null>(null);
  const seedRef = useRef<{ question: string; answer: string } | null>(null);
  const sessionId = useMemo(() => getSessionId(), []);
  const { summary: usage, refresh: refreshUsage } = useUsageSummary(sessionId);

  useEffect(() => {
    let cancelled = false;
    setMeta(null);
    setDoc(null);
    setError(null);
    setCards([]);
    setStickies([]);
    setDrawerMsgs([]);
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
    // 跳转失败不得静默（M0 缺陷 #14）：目录项指向解析结果里不存在的章节时给出可见提示
    const ok = handleRef.current?.jumpTo(item) ?? false;
    setJumpHint(ok ? null : `「${item.title}」在解析结果里没有对应正文，无法跳转`);
  }, []);

  // 提示 4s 后自动消失
  useEffect(() => {
    if (!jumpHint) return;
    const timer = window.setTimeout(() => setJumpHint(null), 4000);
    return () => window.clearTimeout(timer);
  }, [jumpHint]);

  /** 段落闪烁 2s（引用 chips/↗原文 回跳；跨 iframe 的 DOM 都可用 Web Animations）。 */
  const flashPara = useCallback((paraId: string) => {
    const anchored = registryRef.current.get(paraId);
    if (!anchored?.el.animate) return;
    anchored.el.animate(
      [{ backgroundColor: "rgba(250,204,21,0.55)" }, { backgroundColor: "rgba(250,204,21,0)" }],
      { duration: 2000, easing: "ease-out" },
    );
  }, []);

  /** 便签/图解的「↗ 原文」与引用 chips：paraId → 跳转 + 高亮（红线 2 引用回跳） */
  const jumpToPara = useCallback(
    (paraId: string) => {
      if (!doc) return;
      const ch = doc.chapters.find((c) => c.paras.some((p) => p.id === paraId));
      if (!ch) return;
      const ok = handleRef.current?.jumpTo({
        id: `para-${paraId}`,
        title: ch.title,
        chapterId: ch.id,
        paraId,
      });
      if (ok === false) {
        setJumpHint("该段落不在可跳转的正文里（解析结果缺这一段）");
        return;
      }
      window.setTimeout(() => flashPara(paraId), 800); // 跨章渲染后落点闪烁
    },
    [doc, flashPara],
  );

  const onLayoutChange = useCallback(() => setLayoutTick((n) => n + 1), []);

  // 章节切换：清笔迹（笔迹属于翻走的那一页）、重算便签
  const chapterId = chapter?.id ?? "";
  // biome-ignore lint/correctness/useExhaustiveDependencies: chapterId 是信号依赖——章节切换即清笔迹
  useEffect(() => {
    setClearToken((n) => n + 1);
  }, [chapterId]);

  // 窗口缩放重算便签（T3.3.1）
  useEffect(() => {
    const onResize = () => setLayoutTick((n) => n + 1);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  // ---------- 涂写提交 → 意图解析 → 转接（T3.1.5 / T3.2.3） ----------

  const onScribbleSubmit = useCallback(
    (s: ScribbleSubmit) => {
      setMode("reading"); // 提交即回阅读模式（T3.6.2 动线收束）
      const host = pageRef.current;
      const registry = registryRef.current;
      const sel = host && selectionRect(s.points, 8, host.clientWidth, host.clientHeight);
      const image =
        host && sel ? composeRegionImage({ root: host, rect: sel, points: s.points }) : null;

      // 候选段落：选区相交(2分)/近邻(1分) 的前 8 个（红线 4：锚点只用 paraId）
      const candidates: { paraId: string; text: string }[] = [];
      if (host && doc && sel) {
        const scored: { score: number; paraId: string }[] = [];
        for (const pid of registry.paraIds()) {
          const anchored = registry.get(pid);
          if (!anchored) continue;
          // 跨 iframe 换算到书页坐标系（epub.js 分栏元素在 iframe 视口内）
          const local = hostLocalRect(anchored.el, host);
          if (local.width < 1 && local.height < 1) continue; // 幽灵锚点（detached 元素 rect 为 0）
          const score = paraScore(local, sel);
          if (score > 0) scored.push({ score, paraId: pid });
        }
        scored.sort((a, b) => b.score - a.score || (a.paraId < b.paraId ? -1 : 1));
        const paraText = new Map(
          doc.chapters.flatMap((c) => c.paras.map((p) => [p.id, p.text] as const)),
        );
        for (const { paraId: pid } of scored.slice(0, 8)) {
          const text = paraText.get(pid);
          if (text) candidates.push({ paraId: pid, text });
        }
      }
      if (candidates.length === 0) {
        setStickies((prev) => [
          ...prev,
          {
            key: `nohit-${Date.now()}`,
            paraId: chapter?.paras[0]?.id ?? "",
            question: s.note || "（圈选提问）",
            state: "failed",
            failNote: "没找到圈选附近的段落，请把圈画在文字上",
          },
        ]);
        return;
      }

      const stickyKey = `qa-${Date.now()}`;
      void parseScribbleIntent(bookId, {
        image: image ?? BLANK_PNG,
        note: s.note,
        chapterId: chapter?.id ?? null,
        candidates,
      })
        .then(async (intent) => {
          refreshUsage();
          if (intent.route === "diagram" && intent.concept) {
            setCards((prev) =>
              prev.some((c) => c.paraId === intent.paraId && c.concept === intent.concept)
                ? prev
                : [
                    ...prev,
                    {
                      key: `${intent.paraId}:${intent.concept}`,
                      paraId: intent.paraId,
                      concept: intent.concept,
                    },
                  ],
            );
            return;
          }
          // qa：乐观占位便签（T3.3.3），答案到达后填充
          setStickies((prev) => [
            ...prev,
            {
              key: stickyKey,
              paraId: intent.paraId,
              question: intent.question,
              state: "pending",
              thumb: image ?? undefined,
            },
          ]);
          const result = await askQuestion(bookId, {
            question: intent.question,
            chapterId: chapter?.id ?? null,
          });
          refreshUsage();
          setStickies((prev) =>
            prev.map((x) =>
              x.key === stickyKey
                ? {
                    ...x,
                    state: "answered",
                    result: {
                      answer: result.answer,
                      citations: result.citations as Citation[],
                      hasBasis: result.hasBasis,
                    },
                  }
                : x,
            ),
          );
        })
        .catch((e: unknown) => {
          refreshUsage();
          setStickies((prev) => [
            ...prev,
            {
              key: stickyKey,
              paraId: candidates[0]?.paraId ?? "",
              question: s.note || "（圈选提问）",
              state: "failed",
              failNote: e instanceof Error ? e.message : "意图解析失败，请重试",
            },
          ]);
        });
    },
    [bookId, doc, chapter, refreshUsage],
  );

  // ---------- 对话抽屉（Slice 3.4） ----------

  const openDrawer = useCallback(
    (
      hint?: string,
      seed?: { question: string; answer: StickyAnswer; thumb?: string; paraId: string },
    ) => {
      if (seed) {
        seedRef.current = { question: seed.question, answer: seed.answer.answer };
        setDrawerHint("便签");
        setDrawerMsgs([
          { id: "seed-q", role: "user", text: seed.question, thumb: seed.thumb },
          {
            id: "seed-a",
            role: "assistant",
            text: seed.answer.answer,
            citations: seed.answer.citations,
          },
        ]);
      } else {
        setDrawerHint(hint ?? chapter?.title ?? "本章");
      }
      setDrawerOpen(true);
    },
    [chapter],
  );

  const sendDrawer = useCallback(
    (text: string) => {
      if (!doc) return;
      const msgId = Date.now();
      setDrawerMsgs((prev) => [...prev, { id: `u-${msgId}`, role: "user", text }]);
      setDrawerBusy(true);
      // 上下文注入（T3.4.4）：从便签进入的首次追问附带该便签问答对
      const seed = seedRef.current;
      const question = seed
        ? `${text}（接着上一问「${seed.question}」，其回答要点：${seed.answer.slice(0, 160)}）`
        : text;
      if (seed) seedRef.current = null;
      askQuestion(bookId, { question, chapterId: chapter?.id ?? null })
        .then((result) => {
          refreshUsage();
          setDrawerMsgs((prev) => [
            ...prev,
            {
              id: `a-${msgId}`,
              role: "assistant",
              text: result.answer,
              citations: result.citations as Citation[],
              failed: !result.hasBasis && result.answer === "书中未涉及",
            },
          ]);
        })
        .catch((e: unknown) => {
          refreshUsage();
          setDrawerMsgs((prev) => [
            ...prev,
            {
              id: `e-${msgId}`,
              role: "assistant",
              text: e instanceof Error ? e.message : "回答失败",
              failed: true,
            },
          ]);
        })
        .finally(() => setDrawerBusy(false));
    },
    [bookId, chapter, doc, refreshUsage],
  );

  // ---------- 快捷键 A / D / Esc（T3.1.6，输入框聚焦一律失效） ----------

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)
      )
        return;
      if (e.key === "a" || e.key === "A")
        setMode((m) => (m === "annotating" ? "reading" : "annotating"));
      else if (e.key === "d" || e.key === "D") setDrawerOpen((v) => !v);
      else if (e.key === "Escape") {
        if (theater) setTheater(null);
        else if (mapOpen) setMapOpen(false);
        else if (drawerOpen) setDrawerOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [theater, mapOpen, drawerOpen]);

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

  // 便签槽（图解卡 + 讲解便签统一进 StickyBoard 定位，T3.3.1）
  const slots: StickySlot[] = [
    ...cards.map((c) => ({
      key: c.key,
      paraId: c.paraId,
      node: (
        <DiagramCard
          bookId={bookId}
          paraId={c.paraId}
          concept={c.concept}
          onOpenTheater={setTheater}
          onJumpToPara={jumpToPara}
          onClose={() => setCards((prev) => prev.filter((x) => x.key !== c.key))}
          onSettled={refreshUsage}
        />
      ),
    })),
    ...stickies.map((s) => ({
      key: s.key,
      paraId: s.paraId,
      node: (
        <StickyCard
          paraId={s.paraId}
          question={s.question}
          state={s.state}
          result={s.result}
          failNote={s.failNote}
          onJumpToPara={jumpToPara}
          onDeepChat={(seed) => openDrawer(undefined, { ...seed, thumb: s.thumb })}
          onClose={() => setStickies((prev) => prev.filter((x) => x.key !== s.key))}
        />
      ),
    })),
  ];

  const stickyLabels: Record<string, string> = {
    ...Object.fromEntries(cards.map((c) => [c.key, `图解 · ${c.concept}`])),
    ...Object.fromEntries(
      stickies.map((s) => [
        s.key,
        `${s.state === "failed" ? "⚠" : "讲解"} · ${s.question.slice(0, 16)}`,
      ]),
    ),
  };

  // 窄屏底部堆叠（T3.3.6）：同内容平铺
  const bottomNotes =
    slots.length > 0 ? slots.map((s) => <div key={s.key}>{s.node}</div>) : undefined;

  return (
    <>
      <ReaderShell
        title={meta.title}
        chapter={chapter}
        toc={doc.toc}
        onJump={onJump}
        pageRef={pageRef}
        onOpenMap={() => setMapOpen(true)}
        modeToggle={
          <div
            className="hidden items-center rounded-lg border border-stone-300 p-0.5 text-[11px] leading-5 md:flex"
            title="阅读 / 圈选模式（快捷键 A；圈选模式下拖拽画圈提问）"
          >
            <button
              type="button"
              className={`rounded-md px-2 ${mode === "reading" ? "bg-purple-600 text-white" : "text-stone-500 hover:bg-stone-100"}`}
              onClick={() => setMode("reading")}
            >
              阅读
            </button>
            <button
              type="button"
              className={`rounded-md px-2 ${mode === "annotating" ? "bg-red-500 text-white" : "text-stone-500 hover:bg-stone-100"}`}
              onClick={() => setMode("annotating")}
            >
              圈选
            </button>
          </div>
        }
        chatEntry={
          <button
            type="button"
            className={`hidden rounded-lg border px-2 py-1 sm:inline-block ${drawerOpen ? "border-purple-400 bg-purple-50 text-purple-700" : "border-stone-200 text-stone-500 hover:bg-stone-100"}`}
            title="对话抽屉（快捷键 D）"
            onClick={() => (drawerOpen ? setDrawerOpen(false) : openDrawer())}
          >
            💬 对话
          </button>
        }
        costBadge={<CostBadge summary={usage} />}
        pageOverlay={
          <ScribbleLayer
            active={mode === "annotating"}
            onSubmit={onScribbleSubmit}
            clearToken={clearToken}
          />
        }
        marginNotes={
          slots.length > 0 ? (
            <StickyBoard
              slots={slots}
              registry={registryRef.current}
              hostRef={pageRef}
              layoutTick={layoutTick}
              chapterId={chapter?.id ?? ""}
              chapterTitle={chapter?.title ?? ""}
              onJumpToPara={jumpToPara}
              stickyLabels={stickyLabels}
            />
          ) : undefined
        }
        bottomNotes={bottomNotes}
      >
        <Reader
          bookId={bookId}
          doc={doc}
          registry={registryRef.current}
          handleRef={handleRef}
          onChapterChange={setChapter}
          onLayoutChange={onLayoutChange}
        />
      </ReaderShell>

      <ChatDrawer
        open={drawerOpen}
        messages={drawerMsgs}
        busy={drawerBusy}
        headerHint={drawerHint}
        usage={usage}
        toc={doc.toc}
        onClose={() => setDrawerOpen(false)}
        onSend={sendDrawer}
        onJumpToPara={(pid) => {
          setDrawerOpen(false); // T3.4.5：抽屉暂收 → 跳转高亮，上下文保留可再呼出
          jumpToPara(pid);
        }}
        onSwitchAnnotate={() => {
          setDrawerOpen(false);
          setMode("annotating");
        }}
        onOpenMap={() => setMapOpen(true)}
      />

      <BookMap
        open={mapOpen}
        toc={doc.toc}
        currentChapterId={chapter?.id}
        onJump={(item) => {
          setMapOpen(false);
          onJump(item);
        }}
        onClose={() => setMapOpen(false)}
      />

      {theater && (
        <Theater
          diagram={theater}
          bookId={bookId}
          onClose={() => setTheater(null)}
          onJumpToPara={jumpToPara}
          onFollowUp={() => {
            const t = theater; // 继续追问（UI §3.4 五要素）：以图解话题为种子开抽屉
            setTheater(null);
            openDrawer(undefined, {
              question: `图解「${t.concept}」`,
              paraId: t.paraId,
              answer: {
                answer: t.explanation || t.summary || "（见图解）",
                citations: t.citations as Citation[],
                hasBasis: true,
              },
            });
          }}
        />
      )}

      {/* 跳转失败提示（禁止静默失败）：目录/引用指向解析结果里不存在的章节或段落 */}
      {jumpHint && (
        <div className="pointer-events-none fixed bottom-6 left-1/2 z-[60] -translate-x-1/2 rounded-lg bg-stone-800/90 px-3 py-2 text-xs text-white shadow-lg">
          {jumpHint}
        </div>
      )}
    </>
  );
}
