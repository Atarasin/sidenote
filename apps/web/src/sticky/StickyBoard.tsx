/**
 * 便签定位板（计划 T3.3.1 / T3.3.5，UI §3.3 / 上游 U-R1）。
 *
 * - 按 paraId 对应 DOM 的 getBoundingClientRect 实时计算便签垂直位置
 *   （挂在右页边相对层内）；同段多卡纵向错位 8px；章节切换/滚动/缩放重算。
 * - 当前页不可见的段落便签不占位（EPUB 分栏/PDF 滚动都会把段落移出视口）。
 * - 底部「本章问答清单」：列出本章全部便签（按 paraId 章前缀过滤），点击定位。
 */
import { useLayoutEffect, useState } from "react";
import type { AnchorRegistry } from "../reader/anchors";
import { hostLocalRect } from "../reader/hostRect";

export interface StickySlot {
  key: string;
  paraId: string;
  node: React.ReactNode;
}

interface Props {
  slots: StickySlot[];
  registry: AnchorRegistry;
  /** 书页宿主（.book-page），坐标基准 */
  hostRef: React.RefObject<HTMLElement | null>;
  /** 渲染器布局变化信号（翻页/滚动/缩放/章节切换时递增） */
  layoutTick: number;
  chapterId: string;
  chapterTitle: string;
  onJumpToPara: (paraId: string) => void;
  stickyLabels: Record<string, string>;
}

interface Placed {
  slot: StickySlot;
  top: number;
}

const EST_CARD_HEIGHT = 190; // 估算卡高（同类卡统一，避免量测回环）

export default function StickyBoard({
  slots,
  registry,
  hostRef,
  layoutTick,
  chapterId,
  chapterTitle,
  onJumpToPara,
  stickyLabels,
}: Props) {
  const [placed, setPlaced] = useState<Placed[]>([]);
  const [listOpen, setListOpen] = useState(false);
  // 本章便签（paraId 前缀 = 章节号，如 c001-p0003 → c001）
  const chapterSlots = slots.filter((s) => s.paraId.startsWith(`${chapterId}-`));

  // biome-ignore lint/correctness/useExhaustiveDependencies: layoutTick 是信号依赖——翻页/滚动/缩放后重算位置
  useLayoutEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const items: Placed[] = [];
    for (const slot of slots) {
      const anchored = registry.get(slot.paraId);
      if (!anchored) continue;
      // 跨 iframe 换算到书页坐标系（epub.js 分栏元素在 iframe 视口内）
      const r = hostLocalRect(anchored.el, host);
      if (r.width < 1 && r.height < 1) continue; // 幽灵锚点（翻页后 detached 的旧元素）
      // 只显示当前可见页内的便签（横向分栏/纵向滚动都会把段落移出）
      const visible =
        r.x < host.clientWidth &&
        r.x + r.width > 0 &&
        r.y < host.clientHeight &&
        r.y + r.height > 0;
      if (!visible) continue;
      items.push({ slot, top: Math.max(4, r.y) });
    }
    items.sort((a, b) => a.top - b.top);
    // 垂直排布：不回叠（上一张估算高度之下），同段多卡再纵向错位 8px
    let prevBottom = 0;
    for (let i = 0; i < items.length; i++) {
      const overlapIdx = items
        .slice(0, i)
        .filter((p) => Math.abs(p.top - items[i].top) < 24).length;
      const top = Math.max(items[i].top + overlapIdx * 8, prevBottom + 8);
      items[i] = { ...items[i], top };
      prevBottom = top + EST_CARD_HEIGHT;
    }
    setPlaced(items);
  }, [slots, registry, hostRef, layoutTick]);

  return (
    <div className="relative h-full">
      {placed.map((p) => (
        <div key={p.slot.key} className="absolute right-0 left-0" style={{ top: p.top }}>
          {p.slot.node}
        </div>
      ))}
      <div className="absolute right-0 bottom-0 left-0 z-10">
        <button
          type="button"
          className="w-full rounded-lg border border-dashed border-stone-300 bg-white/80 px-2 py-1 text-[11px] text-stone-500 hover:bg-white"
          onClick={() => setListOpen((v) => !v)}
        >
          📋 本章问答清单（{chapterSlots.length}）
        </button>
        {listOpen && (
          <div className="mt-1 max-h-56 overflow-y-auto rounded-lg border border-stone-200 bg-white p-2 shadow-lg">
            <p className="mb-1 text-[10px] text-stone-400">{chapterTitle}</p>
            {chapterSlots.length === 0 && (
              <p className="text-[11px] text-stone-400">本章还没有便签</p>
            )}
            {chapterSlots.map((s) => (
              <button
                key={s.key}
                type="button"
                className="block w-full truncate rounded px-1.5 py-1 text-left text-[11px] text-stone-600 hover:bg-stone-100"
                onClick={() => onJumpToPara(s.paraId)}
              >
                {stickyLabels[s.key] ?? s.paraId}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
