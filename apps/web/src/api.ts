import type { BookDoc, BookFileMeta } from "@shared/types/bookdoc";
/**
 * 后端 API 客户端。开发态走 Vite 代理（/api → 127.0.0.1:8787）。
 */
import { z } from "zod";

const bookFileMetaSchema = z.object({
  bookId: z.string().regex(/^[0-9a-f]{16}$/),
  title: z.string(),
  format: z.enum(["epub", "pdf"]),
  fileHash: z.string(),
  fileName: z.string(),
  sizeBytes: z.number().int(),
  addedAt: z.string(),
  parseStatus: z.enum(["pending", "parsing", "success", "failed"]),
  parseError: z.string().nullable().optional(),
  chaptersCount: z.number().int(),
  parasCount: z.number().int(),
});

async function jsonOrThrow<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try {
      const body = (await resp.json()) as { detail?: string };
      if (body?.detail) detail = body.detail;
    } catch {
      /* keep status text */
    }
    throw new Error(detail);
  }
  return (await resp.json()) as T;
}

export async function uploadBook(file: File): Promise<BookFileMeta> {
  const form = new FormData();
  form.append("file", file);
  const resp = await fetch("/api/books", { method: "POST", body: form });
  return bookFileMetaSchema.parse(await jsonOrThrow(resp));
}

export async function listBooks(): Promise<BookFileMeta[]> {
  const resp = await fetch("/api/books");
  return z.array(bookFileMetaSchema).parse(await jsonOrThrow(resp));
}

export async function getBook(bookId: string): Promise<BookFileMeta> {
  const resp = await fetch(`/api/books/${bookId}`);
  return bookFileMetaSchema.parse(await jsonOrThrow(resp));
}

export async function getBookdoc(bookId: string): Promise<BookDoc> {
  const resp = await fetch(`/api/books/${bookId}/bookdoc`);
  return jsonOrThrow<BookDoc>(resp);
}

export function figureUrl(bookId: string, imgPath: string): string {
  const fileName = imgPath.split("/").pop() ?? imgPath;
  return `/api/books/${bookId}/figures/${fileName}`;
}

// ---------- M1 问答（M3 便签卡与对话抽屉消费） ----------

export interface Citation {
  paraId: string;
  quote: string;
}

export interface AskResult {
  answer: string;
  citations: Citation[];
  hasBasis: boolean;
  witnessUsed: boolean;
  chapterId: string | null;
  provider: string;
  retried: boolean;
}

export async function askQuestion(
  bookId: string,
  payload: { question: string; chapterId?: string | null },
): Promise<AskResult> {
  const resp = await fetch(`/api/books/${bookId}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...payload, sessionId: getSessionId() }),
  });
  return jsonOrThrow<AskResult>(resp);
}

// ---------- M3 涂写意图解析 ----------

export interface ScribbleIntent {
  paraId: string;
  question: string;
  route: "qa" | "diagram";
  concept: string;
}

export async function parseScribbleIntent(
  bookId: string,
  payload: {
    image: string;
    note: string;
    chapterId?: string | null;
    candidates: { paraId: string; text: string }[];
  },
): Promise<ScribbleIntent> {
  const sessionId = getSessionId();
  const resp = await fetch(`/api/books/${bookId}/scribbles/intent`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...payload, sessionId }),
  });
  return jsonOrThrow<ScribbleIntent>(resp);
}

// ---------- M3 费用与限流（/api/usage/summary） ----------

export interface UsageSummary {
  totalCalls: number;
  okCalls: number;
  failedCalls: number;
  totalCostCny: number;
  promptTokens: number;
  completionTokens: number;
  cacheHitTokens: number;
  cacheHitRate: number;
  rateLimit: { used: number; limit: number; limited: boolean; resetAt: number };
}

export async function fetchUsageSummary(sessionId: string): Promise<UsageSummary> {
  const resp = await fetch(`/api/usage/summary?sessionId=${encodeURIComponent(sessionId)}`);
  return jsonOrThrow<UsageSummary>(resp);
}

/** 会话标识（本地生成持久化；与 diagrams 模块共用一份）。 */
export function getSessionId(): string {
  const KEY = "sidenote.sessionId";
  let id = window.localStorage.getItem(KEY);
  if (!id) {
    id = `s-${Math.random().toString(36).slice(2, 10)}`;
    window.localStorage.setItem(KEY, id);
  }
  return id;
}
