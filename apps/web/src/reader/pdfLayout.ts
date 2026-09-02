/**
 * PDF 文本层放置数学（纯函数，可单测）。
 * 流程：measure（绝对页坐标）→ unionBox（段落盒）→ 按「段落盒原点」相对放置 span。
 * span 的最终绝对位置 = 盒原点 + 相对偏移，必须等于 item 的绝对坐标。
 */

export interface ItemGeometry {
  left: number;
  top: number;
  right: number;
  bottom: number;
  fontHeight: number;
}

export interface Box {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

export function unionBox(geometries: ItemGeometry[]): Box {
  const left = Math.min(...geometries.map((g) => g.left));
  const top = Math.min(...geometries.map((g) => g.top));
  const right = Math.max(...geometries.map((g) => g.right));
  const bottom = Math.max(...geometries.map((g) => g.bottom));
  return { left, top, right, bottom };
}

/** span 相对段落盒原点的偏移：恒等于 item 绝对坐标 − 盒原点。 */
export function spanOffset(
  g: ItemGeometry,
  origin: Pick<Box, "left" | "top">,
): { left: number; top: number } {
  return { left: g.left - origin.left, top: g.top - origin.top };
}
