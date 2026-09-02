/**
 * 段落锚点注册表（计划 T0.3.3）：paraId → 渲染层 DOM 元素。
 * 供目录跳转、便签定位、引用回跳（M3）复用；锚点体系只有 BookDoc paraId 一套（红线 4）。
 */

export interface AnchoredNode {
  el: HTMLElement;
  chapterId: string;
}

export class AnchorRegistry {
  private map = new Map<string, AnchoredNode>();

  register(paraId: string, el: HTMLElement, chapterId: string): void {
    this.map.set(paraId, { el, chapterId });
  }

  get(paraId: string): AnchoredNode | undefined {
    return this.map.get(paraId);
  }

  /** 清空某章的锚点（paraId 前缀 = 章节号，如 c001-p0003 → c001）。 */
  clearChapter(chapterId: string): void {
    for (const key of this.map.keys()) {
      if (key.startsWith(`${chapterId}-`)) this.map.delete(key);
    }
  }

  clear(): void {
    this.map.clear();
  }

  paraIds(): string[] {
    return [...this.map.keys()];
  }
}
