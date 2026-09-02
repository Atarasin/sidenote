import type { TocItem } from "@shared/types/bookdoc";
/**
 * 对话抽屉（计划 Slice 3.4，UI 文档 U5 / §3.5，决策 D4）。
 *
 * - 浮层右缘滑出 min(420px, 40vw)，覆盖不挤压书页（UI §6-U5 布局不变性）；
 *   默认关闭，任何状态不自动弹出。
 * - 三入口在父组件（顶栏按钮 / 便签「展开深聊」/ 快捷键 D）；✕/Esc/再按 D 关闭。
 * - 内容三段：头部（标题 + 全书地图 + ✕ + 费用）／对话流／输入行（✏️ 切圈选 + 单行输入）。
 * - 用户消息带圈选截图缩略图与附言；AI 消息带引用 chips 与标注；自动滚底、上滚停止跟随。
 */
import { useEffect, useRef, useState } from "react";
import type { Citation, UsageSummary } from "../api";

export interface DrawerMessage {
  id: string | number;
  role: "user" | "assistant";
  text: string;
  thumb?: string; // 圈选截图缩略图（dataURL）
  citations?: Citation[];
  failed?: boolean;
}

interface Props {
  open: boolean;
  messages: DrawerMessage[];
  busy: boolean;
  headerHint: string;
  usage: UsageSummary | null;
  toc: TocItem[];
  onClose: () => void;
  onSend: (text: string) => void;
  onJumpToPara: (paraId: string) => void;
  onSwitchAnnotate: () => void;
  onOpenMap: () => void;
}

export default function ChatDrawer({
  open,
  messages,
  busy,
  headerHint,
  usage,
  onClose,
  onSend,
  onJumpToPara,
  onSwitchAnnotate,
  onOpenMap,
}: Props) {
  const [input, setInput] = useState("");
  const [follow, setFollow] = useState(true);
  const flowRef = useRef<HTMLDivElement>(null);

  // biome-ignore lint/correctness/useExhaustiveDependencies: messages/busy 是信号依赖——新消息到达时滚底
  useEffect(() => {
    if (follow && flowRef.current) {
      flowRef.current.scrollTop = flowRef.current.scrollHeight;
    }
  }, [messages, busy, follow]);

  if (!open) return null;

  const cost = usage ? `¥${usage.totalCostCny.toFixed(2)} · 本会话` : "¥0.00 · 本会话";

  return (
    <aside
      className="fixed top-0 right-0 bottom-0 z-40 flex flex-col border-l border-stone-300 bg-white shadow-[-8px_0_24px_rgba(0,0,0,0.12)]"
      style={{ width: "min(420px, 40vw)" }}
      aria-label="对话抽屉"
    >
      {/* 头部（T3.4.3：标题 + 全书地图 + ✕ + 费用同步） */}
      <header className="flex h-10 shrink-0 items-center gap-2 border-b border-stone-200 px-3 text-xs text-stone-500">
        <span className="min-w-0 flex-1 truncate">
          对话 · 接着<span className="text-stone-700">{headerHint}</span>聊
        </span>
        <span
          title={`生成 ${usage?.rateLimit.used ?? 0}/${usage?.rateLimit.limit ?? 0} 次 · 缓存命中 ${Math.round((usage?.cacheHitRate ?? 0) * 100)}%`}
        >
          {cost}
        </span>
        <button
          type="button"
          className="rounded border border-stone-200 px-1.5 py-0.5 hover:bg-stone-100"
          onClick={onOpenMap}
        >
          全书地图
        </button>
        <button
          type="button"
          className="rounded px-1 text-stone-400 hover:bg-stone-100 hover:text-stone-600"
          onClick={onClose}
          aria-label="关闭对话抽屉"
        >
          ✕
        </button>
      </header>

      {/* 对话流 */}
      <div
        ref={flowRef}
        className="min-h-0 flex-1 space-y-3 overflow-y-auto bg-[#faf9f6] p-3"
        onScroll={(e) => {
          const el = e.currentTarget;
          setFollow(el.scrollHeight - el.scrollTop - el.clientHeight < 40);
        }}
      >
        {messages.length === 0 && (
          <p className="pt-8 text-center text-xs text-stone-400">
            还没有对话。圈选书页内容提问，或在输入行补一句话。
          </p>
        )}
        {messages.map((m) => (
          <div key={m.id} className={m.role === "user" ? "text-right" : "text-left"}>
            {m.role === "user" ? (
              <div className="inline-block max-w-[92%] rounded-xl bg-purple-600/90 px-3 py-2 text-left text-xs leading-5 text-white">
                {m.thumb && (
                  <img
                    src={m.thumb}
                    alt="圈选截图"
                    className="mb-1 max-h-32 rounded border border-white/40 object-contain"
                  />
                )}
                {m.text || "（圈选提问）"}
              </div>
            ) : (
              <div className="inline-block max-w-[92%] rounded-xl border border-stone-200 bg-white px-3 py-2 text-xs leading-5 text-stone-700">
                {m.failed ? (
                  <span className="text-amber-700">{m.text}</span>
                ) : (
                  <>
                    <p className="whitespace-pre-wrap">{m.text}</p>
                    {m.citations && m.citations.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1">
                        {m.citations.map((c) => (
                          <button
                            key={`${m.id}-${c.paraId}-${c.quote.slice(0, 6)}`}
                            type="button"
                            title={c.quote}
                            className="max-w-full truncate rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[10px] text-stone-600 hover:bg-amber-100"
                            onClick={() => onJumpToPara(c.paraId)}
                          >
                            {c.paraId} · {c.quote.slice(0, 10)}…
                          </button>
                        ))}
                      </div>
                    )}
                    <p className="mt-1.5 text-[10px] text-stone-400">辅助理解，以原文为准</p>
                  </>
                )}
              </div>
            )}
          </div>
        ))}
        {busy && (
          <div className="text-left">
            <div className="inline-block rounded-xl border border-stone-200 bg-white px-3 py-2 text-xs text-stone-400">
              思考中…
            </div>
          </div>
        )}
      </div>

      {/* 输入行（✏️ 切圈选 + 单行文本 + 发送） */}
      <footer className="flex shrink-0 items-center gap-2 border-t border-stone-200 p-2">
        <button
          type="button"
          className="rounded-lg border border-stone-200 px-2 py-1 text-sm hover:bg-stone-100"
          title="切换到圈选模式（A）"
          onClick={onSwitchAnnotate}
        >
          ✏️
        </button>
        <input
          className="min-w-0 flex-1 rounded-lg border border-stone-200 px-2 py-1.5 text-xs"
          placeholder="补一句话（可不填，直接圈选也行）"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            e.stopPropagation(); // 输入框内按键不触发全局快捷键
            if (e.key === "Enter" && input.trim() && !busy) {
              onSend(input.trim());
              setInput("");
            }
          }}
        />
        <button
          type="button"
          className="rounded-lg bg-purple-600 px-3 py-1.5 text-xs text-white hover:bg-purple-500 disabled:opacity-40"
          disabled={!input.trim() || busy}
          onClick={() => {
            if (input.trim()) {
              onSend(input.trim());
              setInput("");
            }
          }}
        >
          发送
        </button>
      </footer>
    </aside>
  );
}
