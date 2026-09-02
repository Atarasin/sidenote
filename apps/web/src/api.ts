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
