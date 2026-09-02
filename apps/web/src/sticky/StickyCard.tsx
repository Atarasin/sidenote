/**
 * AI 讲解便签卡（计划 T3.3.2 / T3.3.3 / T3.3.4，UI 文档 U3 / §3.3）。
 *
 * - 三态：pending（乐观占位骨架）/ answered / failed（含限流文案，禁止静默失败）。
 * - 引用 chips：{paraId, quote}[] 全量渲染，点击滚动到段落并闪烁 2s（红线 2 回跳）。
 * - 标注行「辅助理解，以原文为准」必带；操作行 ↗ 原文 / 展开深聊。
 */
import type { Citation } from "../api";

export interface StickyAnswer {
  answer: string;
  citations: Citation[];
  hasBasis: boolean;
}

interface Props {
  paraId: string;
  question: string;
  state: "pending" | "answered" | "failed";
  result?: StickyAnswer;
  failNote?: string;
  onJumpToPara: (paraId: string) => void;
  onDeepChat?: (seed: { question: string; answer: StickyAnswer; paraId: string }) => void;
  onClose: () => void;
}

export function questionDigest(q: string): string {
  const t = q.trim().replace(/\s+/g, " ");
  return t.length <= 14 ? t : `${t.slice(0, 14)}…`;
}

export default function StickyCard({
  paraId,
  question,
  state,
  result,
  failNote,
  onJumpToPara,
  onDeepChat,
  onClose,
}: Props) {
  return (
    <div className="w-full rounded-xl border border-amber-300 bg-amber-50 p-3 text-stone-800 shadow-sm">
      <div className="mb-2 flex items-center gap-2 text-xs font-semibold">
        <span>📌</span>
        <span className="truncate">讲解 · {questionDigest(question)}</span>
        <button
          type="button"
          className="ml-auto rounded px-1 text-stone-400 hover:bg-amber-100"
          onClick={onClose}
          aria-label="关闭便签"
        >
          ✕
        </button>
      </div>

      <div className="min-h-16 rounded-lg bg-white/70 p-2 text-xs leading-5">
        {state === "pending" && (
          <div className="flex h-16 flex-col items-center justify-center gap-2">
            <div className="h-4 w-4 animate-spin rounded-full border-2 border-amber-300 border-t-transparent" />
            <span className="text-[11px] text-stone-500">正在结合原文解答…</span>
          </div>
        )}
        {state === "failed" && (
          <p className="text-[11px] text-amber-700">{failNote || "回答失败，稍后可重新圈选提问"}</p>
        )}
        {state === "answered" && result && (
          <>
            {!result.hasBasis ? (
              <p className="text-stone-500">书中未涉及</p>
            ) : (
              <p className="max-h-40 overflow-y-auto text-stone-700">{result.answer}</p>
            )}
            {result.citations.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {result.citations.map((c) => (
                  <button
                    key={`${c.paraId}-${c.quote.slice(0, 8)}`}
                    type="button"
                    title={c.quote}
                    className="max-w-full truncate rounded-full border border-amber-200 bg-amber-100/70 px-2 py-0.5 text-[10px] text-stone-600 hover:bg-amber-200"
                    onClick={() => onJumpToPara(c.paraId)}
                  >
                    {c.paraId} · {c.quote.slice(0, 10)}…
                  </button>
                ))}
              </div>
            )}
          </>
        )}
      </div>

      <p className="mt-2 border-t border-amber-200 pt-1.5 text-[10px] text-stone-500">
        辅助理解，以原文为准
      </p>

      <div className="mt-1.5 flex items-center gap-2 text-[11px]">
        <button
          type="button"
          className="rounded bg-white/80 px-2 py-0.5 hover:bg-white"
          onClick={() => onJumpToPara(paraId)}
        >
          ↗ 原文 {paraId}
        </button>
        <button
          type="button"
          className="rounded bg-white/80 px-2 py-0.5 hover:bg-white disabled:opacity-40"
          disabled={state !== "answered"}
          onClick={() => result && onDeepChat?.({ question, answer: result, paraId })}
        >
          💬 展开深聊
        </button>
      </div>
    </div>
  );
}
