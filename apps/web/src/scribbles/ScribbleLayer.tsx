/**
 * 涂写层（计划 T3.1.1~T3.1.5，UI 文档 U2 / §3.2，上游 §3.5）。
 *
 * - 透明 Canvas 覆盖书页：笔迹红色 #ef4444；阅读模式笔迹照常显示但不再收新笔（pointer-events: none）。
 * - 圈选模式按住拖拽画圈，松开成一次圈选（拖拽幅度过小视为误触丢弃）。
 * - 圈旁单行附言气泡：留空直发或补一句话；Esc/点击圈外取消（该笔迹一并撤销）。
 * - 提交时由父组件做截图合成与意图解析（见 composeImage / ReaderPage）。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { STROKE_COLOR } from "./composeImage";
import { type Point, isMeaningfulStroke, selectionRect } from "./geometry";

export interface ScribbleSubmit {
  points: Point[];
  note: string;
}

interface Props {
  /** 圈选模式开关（reading 时只显示不交互） */
  active: boolean;
  onSubmit: (s: ScribbleSubmit) => void;
  /** 章节切换时由父组件递增，清空笔迹 */
  clearToken: number;
}

interface Stroke {
  points: Point[];
}

export default function ScribbleLayer({ active, onSubmit, clearToken }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const hostRef = useRef<HTMLElement | null>(null);
  const noteInputRef = useRef<HTMLInputElement>(null);
  const strokesRef = useRef<Stroke[]>([]);
  const drawingRef = useRef<Point[] | null>(null);
  const [pending, setPending] = useState<{ points: Point[]; x: number; y: number } | null>(null);
  const [note, setNote] = useState("");

  // 宿主 = 本层外层容器（.book-page）：坐标与尺寸基准
  useEffect(() => {
    hostRef.current = canvasRef.current?.parentElement?.parentElement ?? null;
  }, []);

  const redraw = useCallback(() => {
    const canvas = canvasRef.current;
    const host = hostRef.current;
    if (!canvas || !host) return;
    const w = host.clientWidth;
    const h = host.clientHeight;
    const dpr = window.devicePixelRatio || 1;
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
    }
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    ctx.strokeStyle = STROKE_COLOR;
    ctx.lineWidth = 2;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    const all = drawingRef.current
      ? [...strokesRef.current, { points: drawingRef.current }]
      : strokesRef.current;
    for (const s of all) {
      ctx.beginPath();
      s.points.forEach((p, i) => (i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y)));
      ctx.stroke();
    }
  }, []);

  // 笔迹清空（章节切换/书切换）
  // biome-ignore lint/correctness/useExhaustiveDependencies: clearToken 是信号依赖——章节切换即清笔迹重画
  useEffect(() => {
    strokesRef.current = [];
    setPending(null);
    setNote("");
    redraw();
  }, [clearToken, redraw]);

  // 尺寸变化重画（不重建笔迹）
  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const ro = new ResizeObserver(() => redraw());
    ro.observe(host);
    return () => ro.disconnect();
  }, [redraw]);

  const localPoint = (e: React.PointerEvent): Point => {
    const host = hostRef.current;
    const r = host?.getBoundingClientRect();
    return { x: e.clientX - (r?.left ?? 0), y: e.clientY - (r?.top ?? 0) };
  };

  const onPointerDown = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (!active || pending) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    drawingRef.current = [localPoint(e)];
    redraw();
  };

  const onPointerMove = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (!drawingRef.current) return;
    drawingRef.current.push(localPoint(e));
    redraw();
  };

  const onPointerUp = () => {
    const pts = drawingRef.current;
    drawingRef.current = null;
    if (!pts || !isMeaningfulStroke(pts)) {
      redraw(); // 点按/微动：丢弃
      return;
    }
    strokesRef.current.push({ points: pts });
    const host = hostRef.current;
    const sel = selectionRect(pts, 8, host?.clientWidth ?? 0, host?.clientHeight ?? 0);
    setPending({ points: pts, x: sel?.x ?? pts[0].x, y: (sel?.y ?? pts[0].y) - 6 });
    redraw();
  };

  const cancelPending = useCallback(() => {
    setPending(null);
    setNote("");
    // 撤销这笔未提交的圈选笔迹
    if (strokesRef.current.length > 0) strokesRef.current.pop();
    redraw();
  }, [redraw]);

  // 气泡出现时聚焦输入框（biome 禁 autoFocus；effect 等价且可控）
  useEffect(() => {
    if (pending) noteInputRef.current?.focus();
  }, [pending]);

  const submitPending = useCallback(() => {
    if (!pending) return;
    onSubmit({ points: pending.points, note: note.trim() });
    setPending(null);
    setNote("");
  }, [pending, note, onSubmit]);

  return (
    <div className="pointer-events-none absolute inset-0 z-10">
      {active && !pending && (
        <div className="absolute top-2 left-1/2 -translate-x-1/2 rounded-full bg-red-500/90 px-3 py-1 text-[11px] text-white shadow">
          圈选模式：按住拖拽画圈提问 · A / Esc 退出
        </div>
      )}
      <canvas
        ref={canvasRef}
        className="h-full w-full"
        style={{
          pointerEvents: active && !pending ? "auto" : "none",
          touchAction: "none",
          cursor: active ? "crosshair" : "inherit",
        }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
      />
      {pending && (
        <div className="absolute inset-0 z-20" onPointerDown={cancelPending}>
          <div
            className="absolute z-30 flex items-center gap-1 rounded-lg border border-red-200 bg-white p-1 shadow-lg"
            style={{ left: pending.x, top: pending.y, transform: "translateY(-100%)" }}
            onPointerDown={(e) => e.stopPropagation()}
          >
            <input
              ref={noteInputRef}
              className="w-56 rounded border border-stone-200 px-2 py-1 text-xs"
              placeholder="补一句话（可不填，直接圈选也行）"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") submitPending();
                else if (e.key === "Escape") cancelPending();
                e.stopPropagation();
              }}
            />
            <button
              type="button"
              className="rounded bg-red-500 px-2 py-1 text-xs text-white hover:bg-red-400"
              onClick={submitPending}
            >
              提问
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
