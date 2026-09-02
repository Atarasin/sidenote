/**
 * 图解剧场模式（计划 T2.6.2 / T2.6.3 / UI 文档 §3.4）。
 * 全屏深色模态：slate-900 画布 + slate-800 底栏；同一组件 HTML 换容器渲染，
 * 不重新生成、不产生新生成调用（缓存不命中新键，UI §6-U4）。
 * 底栏必含：一句话结论 + 「辅助理解，以原文为准」+ ↗ 回到原文 + 继续追问 + ✕。
 * 关闭：✕ / Esc，回到触发点原位（由父组件保持卡片状态实现）。
 */
import { useEffect } from "react";
import SandboxFrame from "./SandboxFrame";
import type { DiagramPayload } from "./types";

const THEATER_FG = "#e2e8f0"; // 深色剧场前景（双容器配色约束）

interface Props {
  diagram: DiagramPayload;
  bookId: string;
  onClose: () => void;
  onJumpToPara?: (paraId: string) => void;
  onFollowUp?: () => void; // 继续追问（M3 接对话抽屉）
}

export default function Theater({ diagram, bookId, onClose, onJumpToPara, onFollowUp }: Props) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA")) return;
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    // biome-ignore lint/a11y/useSemanticElements: 自绘全屏模态需自定义焦点/Esc 行为，不用原生 <dialog>
    <div className="fixed inset-0 z-50 flex flex-col bg-slate-900/97" role="dialog" aria-modal>
      {/* 画布：同一沙箱组件换容器渲染（不重新生成） */}
      <div
        className="flex min-h-0 flex-1 items-center justify-center p-8"
        style={{ color: THEATER_FG }}
      >
        {diagram.kind === "interactive" && diagram.componentHtml ? (
          <div className="h-full max-h-[70vh] w-full max-w-5xl">
            <SandboxFrame
              html={diagram.componentHtml}
              color={THEATER_FG}
              title={`剧场 · ${diagram.concept}`}
            />
          </div>
        ) : (
          <img
            src={`/api/books/${bookId}/diagrams-files/${diagram.staticImage.split("/").pop()}`}
            alt={`${diagram.concept} 静态图解`}
            className="max-h-[70vh] max-w-5xl object-contain"
          />
        )}
      </div>

      {/* 底栏（T2.6.3：必含五要素） */}
      <footer className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-1 bg-slate-800 px-6 py-3 text-xs text-slate-200">
        <span className="min-w-0 flex-1 truncate">
          <span className="font-medium">{diagram.concept}：</span>
          {diagram.summary}
        </span>
        <span className="text-[10px] text-slate-400">辅助理解，以原文为准</span>
        <button
          type="button"
          className="rounded border border-slate-600 px-2 py-0.5 hover:bg-slate-700"
          onClick={() => onJumpToPara?.(diagram.paraId)}
        >
          ↗ 回到原文 {diagram.paraId}
        </button>
        <button
          type="button"
          className="rounded border border-slate-600 px-2 py-0.5 hover:bg-slate-700 disabled:opacity-40"
          disabled
          title="对话抽屉将在 M3 接入"
          onClick={onFollowUp}
        >
          继续追问
        </button>
        <button
          type="button"
          className="rounded border border-slate-600 px-2 py-0.5 hover:bg-slate-700"
          onClick={onClose}
          aria-label="关闭剧场"
        >
          ✕
        </button>
      </footer>
    </div>
  );
}
