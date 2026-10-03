/**
 * 涂写层（计划 T3.1.1~T3.1.5，UI 文档 U2 / §3.2，上游 §3.5）。
 *
 * - 透明 Canvas 覆盖书页：笔迹红色 #ef4444；阅读模式笔迹照常显示但不再收新笔（pointer-events: none）。
 * - 圈选模式按住拖拽画圈，松开成一次圈选（拖拽幅度过小视为误触丢弃）。
 * - 圈旁单行附言气泡：留空直发或补一句话；Esc/点击圈外取消（该笔迹一并撤销）。
 * - 提交时由父组件做截图合成与意图解析（见 composeImage / ReaderPage）。
 *
 * 坐标系（缺陷 16）：PDF 的滚动发生在阅读器内层 overflow-auto 容器（wrapRef）里，
 * 而本层覆盖在不滚动的 .book-page 上——笔迹按视口坐标存的话，滚轮一滚圈就漂离原文。
 * 因此笔迹与气泡一律按「内容坐标」（视口坐标 + 滚动偏移）存，绘制/定位时减去当前
 * 偏移，提交时换算回当时的视口坐标——composeRegionImage 与段落命中都按提交时视口
 * 几何取值，契约不变。
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
  /**
   * 书页内容的真实滚动容器（PDF 为 wrapRef；EPUB 分栏无滚动，不传即可）。
   * 涂写层不在该容器的滚动子树内，笔迹锚定内容就必须显式感知它的偏移与滚动事件。
   */
  scrollHostRef?: React.RefObject<HTMLElement | null>;
}

interface Stroke {
  points: Point[];
}

interface Pending {
  points: Point[];
  x: number;
  y: number;
  /** 气泡放圈上方（默认）；圈贴内容顶放不下时翻到圈下方 */
  above: boolean;
}

export default function ScribbleLayer({ active, onSubmit, clearToken, scrollHostRef }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const hostRef = useRef<HTMLElement | null>(null);
  const noteInputRef = useRef<HTMLInputElement>(null);
  const strokesRef = useRef<Stroke[]>([]);
  const drawingRef = useRef<Point[] | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [note, setNote] = useState("");
  // 内容滚动偏移的渲染镜像：滚动事件驱动，气泡跟随内容重定位
  const [scrollOffset, setScrollOffset] = useState<Point>({ x: 0, y: 0 });

  // 宿主 = 本层外层容器（.book-page）：坐标与尺寸基准
  useEffect(() => {
    hostRef.current = canvasRef.current?.parentElement?.parentElement ?? null;
  }, []);

  const offsets = useCallback((): Point => {
    const sc = scrollHostRef?.current;
    return sc ? { x: sc.scrollLeft, y: sc.scrollTop } : { x: 0, y: 0 };
  }, [scrollHostRef]);

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
    const o = offsets();
    const all = drawingRef.current
      ? [...strokesRef.current, { points: drawingRef.current }]
      : strokesRef.current;
    for (const s of all) {
      ctx.beginPath();
      s.points.forEach((p, i) =>
        i === 0 ? ctx.moveTo(p.x - o.x, p.y - o.y) : ctx.lineTo(p.x - o.x, p.y - o.y),
      );
      ctx.stroke();
    }
  }, [offsets]);

  // 内容滚动 → 笔迹与气泡跟着内容走（重画 + 偏移镜像更新）
  useEffect(() => {
    const scroller = scrollHostRef?.current;
    if (!scroller) return;
    const onScroll = () => {
      setScrollOffset({ x: scroller.scrollLeft, y: scroller.scrollTop });
      redraw();
    };
    scroller.addEventListener("scroll", onScroll, { passive: true });
    return () => scroller.removeEventListener("scroll", onScroll);
  }, [scrollHostRef, redraw]);

  // 笔迹清空（章节切换/书切换）
  // biome-ignore lint/correctness/useExhaustiveDependencies: clearToken 是信号依赖——章节切换即清笔迹重画
  useEffect(() => {
    strokesRef.current = [];
    setPending(null);
    setNote("");
    redraw();
  }, [clearToken, redraw]);

  // 模式切换：丢弃画到一半的笔迹（评审 P2-4：切阅读模式后半截笔迹滞留）
  useEffect(() => {
    if (!active) {
      drawingRef.current = null;
      redraw();
    }
  }, [active, redraw]);

  // 尺寸变化重画（不重建笔迹）
  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const ro = new ResizeObserver(() => redraw());
    ro.observe(host);
    return () => ro.disconnect();
  }, [redraw]);

  // 笔迹按内容坐标存：视口坐标 + 滚动偏移（EPUB 无滚动容器时偏移恒为 0）
  const localPoint = (e: React.PointerEvent): Point => {
    const host = hostRef.current;
    const r = host?.getBoundingClientRect();
    const o = offsets();
    return { x: e.clientX - (r?.left ?? 0) + o.x, y: e.clientY - (r?.top ?? 0) + o.y };
  };

  // 涂写层不在滚动链上，滚轮默认够不到书页内容：手动转发给滚动容器，
  // 圈选模式与气泡打开期间滚动不中断（滚动后笔迹/气泡随内容重定位）
  const forwardWheel = (e: React.WheelEvent) => {
    const scroller = scrollHostRef?.current;
    if (!scroller) return;
    scroller.scrollTop += e.deltaY;
    scroller.scrollLeft += e.deltaX;
  };

  const onPointerDown = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (!active || pending) return;
    try {
      e.currentTarget.setPointerCapture(e.pointerId);
    } catch {
      /* 指针已释放/合成事件：捕获失败不阻断起笔 */
    }
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
    const o = offsets();
    // 选区裁剪进内容坐标空间（外扩后的边界是「视口尺寸 + 滚动偏移」）
    const sel = selectionRect(
      pts,
      8,
      (host?.clientWidth ?? 0) + o.x,
      (host?.clientHeight ?? 0) + o.y,
    );
    // 气泡默认放圈上方；圈贴着内容顶（上方放不下气泡）时翻到圈下方
    const above = sel ? sel.y - o.y >= 56 : true;
    setPending({
      points: pts,
      x: sel?.x ?? pts[0].x,
      y: sel ? (above ? sel.y - 6 : sel.y + sel.height + 6) : pts[0].y,
      above,
    });
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
    // 提交换算回「此刻视口」坐标：截图合成与段落命中都按提交时的视口几何取值
    const o = offsets();
    onSubmit({
      points: pending.points.map((p) => ({ x: p.x - o.x, y: p.y - o.y })),
      note: note.trim(),
    });
    setPending(null);
    setNote("");
  }, [pending, note, onSubmit, offsets]);

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
        onWheel={forwardWheel}
      />
      {pending && (
        // 缺陷 17：遮罩必须显式 pointer-events-auto——外层容器是 pointer-events-none，
        // 继承下来输入框/按钮点击全部穿透，气泡一开就「没反应」
        <div
          className="pointer-events-auto absolute inset-0 z-20"
          onPointerDown={cancelPending}
          onWheel={forwardWheel}
        >
          <div
            className="absolute z-30 flex items-center gap-1 rounded-lg border border-red-200 bg-white p-1 shadow-lg"
            style={{
              left: pending.x - scrollOffset.x,
              top: pending.y - scrollOffset.y,
              ...(pending.above ? { transform: "translateY(-100%)" } : {}),
            }}
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
