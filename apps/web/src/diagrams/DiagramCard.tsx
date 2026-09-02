/**
 * 图解小卡（计划 T2.6.1 / T2.2.3 / T2.3.2 / UI 文档 §3.3-§3.4）。
 *
 * 状态机（上游 §3.4 主链路）：生成中 → 交互组件 →（沙箱检测失败 → 自动修复重试 1 次）
 * →（仍失败 → 静态图降级，标注不变）→ 限流显式提示（禁止静默失败）。
 * 失败计数封顶（sandboxFailAction）：第 1 次失败修复、第 2 次起必降级，
 * 杜绝「修复返回同一坏组件 → 再失败 → 再修复」的死循环（评审 D2）。
 * 标注行「辅助理解，以原文为准」必带（红线 2）；讲解默认折叠可展开。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import SandboxFrame from "./SandboxFrame";
import { createDiagram, degradeDiagram } from "./api";
import { sandboxFailAction } from "./failAction";
import type { DiagramPayload } from "./types";

type Phase = "generating" | "repairing" | "degrading" | "interactive" | "degraded" | "limited";

interface Props {
  bookId: string;
  paraId: string;
  concept: string;
  onOpenTheater?: (d: DiagramPayload) => void;
  onJumpToPara?: (paraId: string) => void;
  onClose?: () => void;
  /** 任一请求落定后触发（M3 费用刷新，S3.5） */
  onSettled?: () => void;
}

const CARD_FG = "#1f2937"; // 浅色小卡前景（双容器配色：剧场由 Theater 提供深色）

export default function DiagramCard({
  bookId,
  paraId,
  concept,
  onOpenTheater,
  onJumpToPara,
  onClose,
  onSettled,
}: Props) {
  const [phase, setPhase] = useState<Phase>("generating");
  const [diagram, setDiagram] = useState<DiagramPayload | null>(null);
  const [failNote, setFailNote] = useState<string>("");
  const [explainOpen, setExplainOpen] = useState(false);
  const [limitedInfo, setLimitedInfo] = useState<string>("");
  const started = useRef(false);
  const failCount = useRef(0);
  const settledRef = useRef(onSettled);
  settledRef.current = onSettled;

  const degrade = useCallback(() => {
    setPhase("degrading");
    return degradeDiagram(bookId, { paraId, concept })
      .then((d) => {
        setDiagram(d);
        setPhase("degraded");
      })
      .catch(() => {
        // 降级请求本身失败：退到无图讲解态（后端缓存里可能有早前降级产物）
        setPhase("degraded");
      })
      .finally(() => settledRef.current?.());
  }, [bookId, paraId, concept]);

  const request = useCallback(
    async (stage: "first" | "repair", failReason = "") => {
      try {
        const result = await createDiagram(bookId, {
          paraId,
          concept,
          repair: stage === "repair",
          failReason,
        });
        if ("limited" in result) {
          setLimitedInfo(`${result.detail}（${result.rateLimit.used}/${result.rateLimit.limit}）`);
          setPhase("limited");
          return result;
        }
        setDiagram(result);
        if (result.kind === "degraded") {
          setPhase("degraded"); // 缓存里已是降级态
        } else if (result.kind === "interactive" && result.componentHtml) {
          setPhase("interactive");
        }
        // kind === "incomplete"（产物不完整/引用未过校验）：不进 interactive，
        // 由调用方按失败处置（修复或降级），绝不渲染空组件白屏（评审 D1）
        return result;
      } finally {
        settledRef.current?.();
      }
    },
    [bookId, paraId, concept],
  );

  const handleFail = useCallback(
    (reason: string) => {
      setFailNote(reason);
      failCount.current += 1;
      if (sandboxFailAction(failCount.current) === "repair") {
        setPhase("repairing");
        void request("repair", reason)
          .then((r) => {
            if (r && !("limited" in r) && r.kind === "incomplete") handleFail(reason);
          })
          .catch(() => degrade());
      } else {
        void degrade(); // T2.2.3 → T2.3.2：修复仍失败，静态图降级
      }
    },
    [request, degrade],
  );

  // started 守卫：依赖数组完整（StrictMode 双跑安全），但首请求只发一次
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void request("first")
      .then((r) => {
        if (r && !("limited" in r) && r.kind === "incomplete") handleFail("生成产物不完整");
      })
      .catch(() => {
        setFailNote("生成请求失败");
        void degrade();
      });
  }, [request, degrade, handleFail]);

  const onSandboxFail = useCallback(
    (reason: string) => {
      if (phase === "interactive" || phase === "repairing") handleFail(reason);
    },
    [phase, handleFail],
  );

  const onSandboxReady = useCallback(() => {
    setFailNote("");
  }, []);

  const explanation = diagram?.explanation || diagram?.summary || "";

  return (
    <div className="w-full rounded-xl border border-amber-300 bg-amber-50 p-3 text-stone-800 shadow-sm">
      {/* 标题行（UI §3.3） */}
      <div className="mb-2 flex items-center gap-2 text-xs font-semibold">
        <span>📌</span>
        <span className="truncate">{`图解 · ${concept}`}</span>
        {diagram?.cached && <span className="text-[10px] font-normal text-stone-400">缓存</span>}
        <button
          type="button"
          className="ml-auto rounded px-1 text-stone-400 hover:bg-amber-100"
          onClick={onClose}
          aria-label="关闭便签"
        >
          ✕
        </button>
      </div>

      {/* 内容区 */}
      <div className="h-40 overflow-hidden rounded-lg bg-white/70">
        {phase === "generating" && <Skeleton label="生成中…" />}
        {phase === "repairing" && <Skeleton label={`渲染失败（${failNote}），修复重试中…`} />}
        {phase === "degrading" && <Skeleton label={`重试仍失败（${failNote}），降级为静态图…`} />}
        {phase === "limited" && (
          <div className="flex h-full items-center justify-center p-3 text-center text-xs text-amber-700">
            {limitedInfo || "已达频率上限，请稍后再试"}
          </div>
        )}
        {phase === "interactive" && diagram?.componentHtml && (
          <SandboxFrame
            html={diagram.componentHtml}
            color={CARD_FG}
            onReady={onSandboxReady}
            onFail={onSandboxFail}
            title={`图解 ${concept}`}
          />
        )}
        {phase === "degraded" && diagram?.staticImage && (
          <img
            src={`/api/books/${bookId}/diagrams-files/${diagram.staticImage.split("/").pop()}`}
            alt={`${concept} 静态图解`}
            className="h-full w-full object-contain"
          />
        )}
        {phase === "degraded" && !diagram?.staticImage && (
          <div className="flex h-full items-center justify-center p-3 text-xs text-stone-500">
            静态图生成失败，见下方文字讲解
          </div>
        )}
      </div>

      {/* 讲解（默认折叠，T2.6.1） */}
      {phase === "degraded" && explanation ? (
        <p className="mt-2 text-xs leading-5 text-stone-700">{explanation}</p>
      ) : (
        explanation && (
          <div className="mt-2">
            <button
              type="button"
              className="text-[11px] text-stone-500 hover:text-stone-700"
              onClick={() => setExplainOpen((v) => !v)}
            >
              {explainOpen ? "收起讲解 ▴" : "展开讲解 ▾"}
            </button>
            {explainOpen && <p className="mt-1 text-xs leading-5 text-stone-700">{explanation}</p>}
          </div>
        )
      )}

      {/* 标注行（红线 2：必带） */}
      <p className="mt-2 border-t border-amber-200 pt-1.5 text-[10px] text-stone-500">
        辅助理解，以原文为准
      </p>

      {/* 操作行（UI §3.3；剧场=T2.6.2，继续追问 M3 接对话抽屉） */}
      <div className="mt-1.5 flex items-center gap-2 text-[11px]">
        <button
          type="button"
          className="rounded bg-white/80 px-2 py-0.5 hover:bg-white disabled:opacity-40"
          disabled={phase !== "interactive" && phase !== "degraded"}
          onClick={() => diagram && onOpenTheater?.(diagram)}
        >
          ⤢ 剧场放大
        </button>
        <button
          type="button"
          className="rounded bg-white/80 px-2 py-0.5 hover:bg-white"
          onClick={() => onJumpToPara?.(paraId)}
        >
          ↗ 原文 {paraId}
        </button>
      </div>
    </div>
  );
}

function Skeleton({ label }: { label: string }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2">
      <div className="h-5 w-5 animate-spin rounded-full border-2 border-amber-300 border-t-transparent" />
      <span className="text-[11px] text-stone-500">{label}</span>
    </div>
  );
}
