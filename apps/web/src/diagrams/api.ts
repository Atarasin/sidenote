/** 图解 API 客户端（M2）。会话标识统一放 ../api（M3 费用呈现共用）。 */

import { getSessionId } from "../api";
import type { DiagramLimitedPayload, DiagramPayload } from "./types";

export { getSessionId };

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
