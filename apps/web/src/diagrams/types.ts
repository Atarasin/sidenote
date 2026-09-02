/** 图解 API 类型（与后端 app/diagrams 对应）。 */

import type { Citation } from "@shared/types/bookdoc";

export interface RateLimitInfo {
  used: number;
  limit: number;
  limited: boolean;
  resetAt: number;
}

export interface DiagramPayload {
  cacheKey: string;
  bookId: string;
  paraId: string;
  concept: string;
  normalized: string;
  kind: "interactive" | "incomplete" | "degraded";
  componentHtml: string;
  staticImage: string;
  explanation: string;
  summary: string;
  citations: Citation[];
  cached: boolean;
  attempts: number;
  provider: string;
  rateLimit: RateLimitInfo;
}

export interface DiagramLimitedPayload {
  limited: true;
  detail: string;
  rateLimit: RateLimitInfo;
}
