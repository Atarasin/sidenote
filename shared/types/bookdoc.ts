/**
 * BookDoc TypeScript 类型定义（与 shared/types/bookdoc.schema.json 保持一致）。
 * 段落 ID 约定：`c{章节序,3位起}-p{段序,4位起}`，如 `c001-p0001`。
 */

export type BookFormat = "epub" | "pdf";

export interface DocMeta {
  bookId: string; // 16 位十六进制（文件 sha256 前 16 位）
  title: string;
  authors?: string[];
  format: BookFormat;
  fileHash: string;
}

export interface TocItem {
  id: string;
  title: string;
  chapterId?: string;
  paraId?: string;
  children?: TocItem[];
}

export interface Para {
  id: string;
  text: string;
  /** PDF 专用：段落首个字符所在页码（0 起），EPUB 无此字段 */
  page?: number;
}

export interface Chapter {
  id: string;
  title: string;
  paras: Para[];
  /** EPUB 专用：spine 文档名（渲染层锚点映射用） */
  href?: string;
}

export interface Figure {
  id: string;
  chapterId: string;
  /** 相对书籍目录的路径，如 `figures/fig-c001-01.png` */
  imgPath: string;
  caption?: string;
}

export interface BookDoc {
  meta: DocMeta;
  toc: TocItem[];
  chapters: Chapter[];
  figures: Figure[];
}

/** 引用（上游红线 2）：{paraId, quote}[]，quote 必须能在对应段落原文中字面对上 */
export interface Citation {
  paraId: string;
  quote: string;
}

/** data/books/<id>/meta.json —— 上传与解析状态记录（不属于 BookDoc 本体） */
export interface BookFileMeta {
  bookId: string;
  title: string;
  format: BookFormat;
  fileHash: string;
  fileName: string;
  sizeBytes: number;
  addedAt: string; // ISO 8601
  parseStatus: "pending" | "parsing" | "success" | "failed";
  parseError?: string | null;
  chaptersCount: number;
  parasCount: number;
}
