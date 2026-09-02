/** 图解 API 客户端（M2）。 */

import type { DiagramLimitedPayload, DiagramPayload } from "./types";

export function getSessionId(): string {
  const KEY = "sidenote.sessionId";
  let id = window.localStorage.getItem(KEY);
  if (!id) {
    id = `s-${Math.random().toString(36).slice(2, 10)}`;
    window.localStorage.setItem(KEY, id);
  }
  return id;
}

export async function createDiagram(
  bookId: string,
  payload: { paraId: string; concept: string; repair?: boolean; failReason?: string },
): Promise<DiagramPayload | DiagramLimitedPayload> {
  const resp = await fetch(`/api/books/${bookId}/diagrams`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...payload, sessionId: getSessionId() }),
  });
  const body = await resp.json();
  if (resp.status === 429) return { limited: true, ...body };
  return body as DiagramPayload;
}

export async function degradeDiagram(
  bookId: string,
  payload: { paraId: string; concept: string },
): Promise<DiagramPayload> {
  const resp = await fetch(`/api/books/${bookId}/diagrams/degrade`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...payload, sessionId: getSessionId() }),
  });
  return (await resp.json()) as DiagramPayload;
}
