/**
 * 跨 iframe 的宿主坐标系换算（M3）。
 *
 * iframe 内元素的 getBoundingClientRect 相对该 iframe 视口，不会自动换算到
 * 顶层；epub.js 分栏还会同时保留多个 iframe（当前栏/预载栏）。这里沿
 * frameElement 链逐层累加偏移，得到元素在书页宿主（.book-page）里的矩形。
 */

export interface HostRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** 元素相对其所在文档链最顶层（主文档）视口的矩形。 */
function viewportRect(el: HTMLElement): {
  left: number;
  top: number;
  width: number;
  height: number;
} {
  const r = el.getBoundingClientRect();
  let left = r.left;
  let top = r.top;
  let win = el.ownerDocument.defaultView;
  while (win && win !== window) {
    const frame = win.frameElement as HTMLElement | null;
    if (!frame) break;
    const fr = frame.getBoundingClientRect();
    left += fr.left;
    top += fr.top;
    win = frame.ownerDocument?.defaultView ?? null;
  }
  return { left, top, width: r.width, height: r.height };
}

/** 元素在宿主（host）局部坐标系中的矩形。 */
export function hostLocalRect(el: HTMLElement, host: HTMLElement): HostRect {
  const hr = host.getBoundingClientRect();
  const v = viewportRect(el);
  return { x: v.left - hr.left, y: v.top - hr.top, width: v.width, height: v.height };
}
