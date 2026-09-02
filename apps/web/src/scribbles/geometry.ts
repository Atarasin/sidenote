/** 涂写几何工具（T3.1.3 / T3.1.5）：笔迹包围盒、选区裁剪、候选段落命中。 */

export interface Point {
  x: number;
  y: number;
}

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** 笔迹包围盒（无点返回 null）。 */
export function strokeBounds(points: Point[]): Rect | null {
  if (points.length === 0) return null;
  let x0 = points[0].x;
  let y0 = points[0].y;
  let x1 = x0;
  let y1 = y0;
  for (const p of points) {
    x0 = Math.min(x0, p.x);
    y0 = Math.min(y0, p.y);
    x1 = Math.max(x1, p.x);
    y1 = Math.max(y1, p.y);
  }
  return { x: x0, y: y0, width: x1 - x0, height: y1 - y0 };
}

/** 选区 = 笔迹包围盒外扩 pad，并裁剪进容器 [0,0,w,h]。 */
export function selectionRect(points: Point[], pad: number, w: number, h: number): Rect | null {
  const b = strokeBounds(points);
  if (!b) return null;
  const x = Math.max(0, b.x - pad);
  const y = Math.max(0, b.y - pad);
  const x2 = Math.min(w, b.x + b.width + pad);
  const y2 = Math.min(h, b.y + b.height + pad);
  if (x2 <= x || y2 <= y) return null;
  return { x, y, width: x2 - x, height: y2 - y };
}

/** 笔迹是否构成一次有效圈选（拖拽距离够长；点按不算）。 */
export function isMeaningfulStroke(points: Point[], minExtent = 12): boolean {
  const b = strokeBounds(points);
  return !!b && (b.width >= minExtent || b.height >= minExtent);
}

export function rectsIntersect(a: Rect, b: Rect): boolean {
  return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
}

/** 段落命中分值：与选区相交得 2 分，垂直距离 ≤ maxGap 得 1 分（近邻兜底）。 */
export function paraScore(para: Rect, sel: Rect, maxGap = 120): number {
  if (rectsIntersect(para, sel)) return 2;
  const dy = para.y < sel.y ? sel.y - (para.y + para.height) : para.y - (sel.y + sel.height);
  const dx = para.x < sel.x ? sel.x - (para.x + para.width) : para.x - (sel.x + sel.width);
  if (dy >= 0 && dy <= maxGap && dx < sel.width) return 1;
  return 0;
}
