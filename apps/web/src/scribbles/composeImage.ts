/**
 * 区域截图合成（T3.1.5）：圈选区域的书页内容 + 红色笔迹 → PNG dataURL。
 *
 * - PDF：书页就是 pdf.js 的 <canvas>，按分辨率比例裁剪 drawImage；
 * - EPUB：书页在 iframe 里，直接截 DOM 需要重序列化；改为把选区内文本行
 *   按原位绘制到白底画布（视觉模型要读的是文字与圈选位置，等价且确定性）。
 * 两条路径最后都叠加同一份笔迹。
 */

import type { Point, Rect } from "./geometry";

export const STROKE_COLOR = "#ef4444";

export interface ComposeInput {
  /** 书页容器（.book-page），选区坐标即相对它 */
  root: HTMLElement;
  rect: Rect;
  points: Point[];
  /** 输出画布最大宽度（px），超出等比缩小 */
  maxWidth?: number;
}

/** 找到与选区相交的渲染 canvas（PDF 路径）；无则返回 null。 */
function findCanvas(root: HTMLElement, rect: Rect): HTMLCanvasElement | null {
  const rootRect = root.getBoundingClientRect();
  for (const canvas of Array.from(root.querySelectorAll("canvas"))) {
    const r = canvas.getBoundingClientRect();
    const local = {
      x: r.left - rootRect.left,
      y: r.top - rootRect.top,
      width: r.width,
      height: r.height,
    };
    if (
      local.x < rect.x + rect.width &&
      rect.x < local.x + local.width &&
      local.y < rect.y + rect.height &&
      rect.y < local.y + local.height
    ) {
      return canvas;
    }
  }
  return null;
}

/** 把一个文本节点按行切 Range（必须用节点所属文档创建，跨文档会抛错）。 */
function textLineRanges(doc: Document, node: Text): Range[] {
  const full = doc.createRange();
  full.selectNodeContents(node);
  const len = node.textContent?.length ?? 0;
  if (len === 0 || len > 2000) return [full];
  // 逐字符探测行顶变化切行（只有与选区相交的节点会走到这里，成本可控）
  const probe = doc.createRange();
  const ranges: Range[] = [];
  let lineStart = 0;
  let lastTop: number | null = null;
  for (let i = 0; i <= len; i++) {
    probe.setStart(node, Math.min(i, len));
    probe.setEnd(node, Math.min(i + 1, len));
    const top = probe.getClientRects()[0]?.top ?? null;
    if (top !== null && lastTop !== null && Math.abs(top - lastTop) > 4) {
      const r = doc.createRange();
      r.setStart(node, lineStart);
      r.setEnd(node, i);
      ranges.push(r);
      lineStart = i;
    }
    if (top !== null) lastTop = top;
  }
  if (lineStart < len) {
    const r = doc.createRange();
    r.setStart(node, lineStart);
    r.setEnd(node, len);
    ranges.push(r);
  }
  return ranges.length ? ranges : [full];
}

/** 与选区相交判定（相对 root 的局部坐标）。 */
function intersects(local: Rect, rect: Rect): boolean {
  return (
    local.x < rect.x + rect.width &&
    rect.x < local.x + local.width &&
    local.y < rect.y + rect.height &&
    rect.y < local.y + local.height + 4
  );
}

/** EPUB：把各 iframe 内选区中的文本行按相对位置画到画布。
 *
 * epub.js 分栏会同时保留多个 iframe（当前栏/预载栏），逐个检查；
 * iframe 内 rect 是该 iframe 视口坐标，需加 iframe 元素在宿主中的偏移。
 */
function paintIframeText(
  ctx: CanvasRenderingContext2D,
  root: HTMLElement,
  rootRect: DOMRect,
  rect: Rect,
): void {
  ctx.font = "14px system-ui, sans-serif";
  ctx.fillStyle = "#111827";
  for (const iframe of Array.from(root.querySelectorAll("iframe"))) {
    const doc = iframe.contentDocument;
    if (!doc?.body) continue;
    const fr = iframe.getBoundingClientRect();
    const originX = fr.left - rootRect.left;
    const originY = fr.top - rootRect.top;
    const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT);
    let node = walker.nextNode() as Text | null;
    while (node) {
      const parent = node.parentElement;
      const tag = parent?.tagName;
      if (parent && (node.textContent ?? "").trim() && tag !== "SCRIPT" && tag !== "STYLE") {
        // 节点级粗筛先行：整节点都不与选区相交就不做逐字符切行
        //（epub.js 载整章 DOM，长章节逐字符 getClientRects 会阻塞主线程）
        const probe = doc.createRange();
        probe.selectNodeContents(node);
        const pr = probe.getBoundingClientRect();
        const nodeLocal = {
          x: pr.left + originX,
          y: pr.top + originY,
          width: pr.width,
          height: pr.height,
        };
        if (nodeLocal.width > 0 && intersects(nodeLocal, rect)) {
          for (const range of textLineRanges(doc, node)) {
            const elRect = range.getBoundingClientRect(); // iframe 视口坐标
            const local = {
              x: elRect.left + originX,
              y: elRect.top + originY,
              width: elRect.width,
              height: elRect.height,
            };
            if (intersects(local, rect)) {
              ctx.fillText(
                range.toString(),
                local.x - rect.x + 2,
                local.y - rect.y + Math.min(local.height, 16),
                Math.max(local.width, 20),
              );
            }
          }
        }
      }
      node = walker.nextNode() as Text | null;
    }
  }
}

/** 合成选区截图：返回 dataURL（失败返回 null，调用方退化为纯附言提交）。 */
export function composeRegionImage(input: ComposeInput): string | null {
  const { root, rect, points } = input;
  const maxWidth = input.maxWidth ?? 800;
  const scale = rect.width > maxWidth ? maxWidth / rect.width : 1;
  const out = document.createElement("canvas");
  out.width = Math.max(2, Math.round(rect.width * scale));
  out.height = Math.max(2, Math.round(rect.height * scale));
  const ctx = out.getContext("2d");
  if (!ctx) return null;
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, out.width, out.height);
  ctx.scale(scale, scale);

  const rootRect = root.getBoundingClientRect();
  const canvas = findCanvas(root, rect);
  if (canvas) {
    // PDF：canvas 分辨率 ≠ CSS 尺寸，按比例映射后裁剪
    const cr = canvas.getBoundingClientRect();
    const pxPerCss = canvas.width / Math.max(cr.width, 1);
    const sx = (rect.x - (cr.left - rootRect.left)) * pxPerCss;
    const sy = (rect.y - (cr.top - rootRect.top)) * pxPerCss;
    try {
      ctx.drawImage(
        canvas,
        sx,
        sy,
        rect.width * pxPerCss,
        rect.height * pxPerCss,
        0,
        0,
        rect.width,
        rect.height,
      );
    } catch {
      /* 画布不可读（理论不会发生，本地同源）→ 留白底 */
    }
  } else {
    paintIframeText(ctx, root, rootRect, rect);
  }

  // 叠加同一份笔迹（红 #ef4444，UI §3.2）
  ctx.strokeStyle = STROKE_COLOR;
  ctx.lineWidth = 2;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.beginPath();
  points.forEach((p, i) => {
    const x = p.x - rect.x;
    const y = p.y - rect.y;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();

  try {
    return out.toDataURL("image/png");
  } catch {
    return null;
  }
}
