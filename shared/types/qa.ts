/** 问答 API 类型（与后端 app/qa/routes.py 的响应一致；M3 便签卡/对话抽屉消费）。 */

import type { Citation } from "./bookdoc";

export interface AskRequest {
  question: string;
  chapterId?: string;
}

export interface AskResult {
  answer: string;
  citations: Citation[];
  hasBasis: boolean;
  witnessUsed: boolean;
  chapterId?: string | null;
  provider: string;
  retried: boolean;
}
