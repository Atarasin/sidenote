/** 全书地图浮层（计划 T3.4.6）：抽屉头部与目录面板双入口，展示目录、点击跳章。 */

import type { TocItem } from "@shared/types/bookdoc";

interface Props {
  open: boolean;
  toc: TocItem[];
  currentChapterId?: string;
  onJump: (item: TocItem) => void;
  onClose: () => void;
}

export default function BookMap({ open, toc, currentChapterId, onJump, onClose }: Props) {
  if (!open) return null;
  return (
    // biome-ignore lint/a11y/useKeyWithClickEvents: 背景点击关闭为辅助操作，主要交互在面板控件内
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-stone-900/30 p-6"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="flex max-h-[70vh] w-full max-w-2xl flex-col rounded-xl bg-white p-5 shadow-2xl">
        <div className="mb-3 flex items-center justify-between text-sm font-semibold text-stone-800">
          全书地图
          <button
            type="button"
            className="rounded px-1 text-stone-400 hover:bg-stone-100 hover:text-stone-600"
            onClick={onClose}
            aria-label="关闭全书地图"
          >
            ✕
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">
          <MapList items={toc} depth={0} currentChapterId={currentChapterId} onJump={onJump} />
        </div>
      </div>
    </div>
  );
}

function MapList({
  items,
  depth,
  currentChapterId,
  onJump,
}: {
  items: TocItem[];
  depth: number;
  currentChapterId?: string;
  onJump: (item: TocItem) => void;
}) {
  return (
    <ul className="space-y-0.5">
      {items.map((item) => (
        <li key={item.id}>
          <button
            type="button"
            className={`block w-full truncate rounded px-2 py-1.5 text-left text-xs hover:bg-stone-100 ${
              item.chapterId === currentChapterId
                ? "bg-purple-50 font-medium text-purple-700"
                : "text-stone-700"
            }`}
            style={{ paddingLeft: `${8 + depth * 16}px` }}
            onClick={() => onJump(item)}
          >
            {item.title}
          </button>
          {item.children && item.children.length > 0 && (
            <MapList
              items={item.children}
              depth={depth + 1}
              currentChapterId={currentChapterId}
              onJump={onJump}
            />
          )}
        </li>
      ))}
    </ul>
  );
}
