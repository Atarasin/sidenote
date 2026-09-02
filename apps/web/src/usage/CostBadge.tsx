/**
 * 费用徽章 + 轮询 hook（计划 Slice 3.5，UI 文档 U6 / 红线 3）。
 *
 * - 顶栏常驻「¥0.42 · 本会话」，hover 明细（生成次数/缓存命中）；
 * - 达会话频率限制 80% 时文字变琥珀色（T3.5.2）；
 * - 15s 轮询 + 手动 refresh()（每次生成/提问后由父组件触发，T3.5.4 联调一致）。
 */
import { useCallback, useEffect, useState } from "react";
import { type UsageSummary, fetchUsageSummary } from "../api";

export function useUsageSummary(sessionId: string) {
  const [summary, setSummary] = useState<UsageSummary | null>(null);

  const refresh = useCallback(() => {
    fetchUsageSummary(sessionId)
      .then(setSummary)
      .catch(() => setSummary(null)); // 接口不可达：保持上次值（顶栏不闪红）
  }, [sessionId]);

  useEffect(() => {
    refresh();
    const t = window.setInterval(refresh, 15_000);
    return () => window.clearInterval(t);
  }, [refresh]);

  return { summary, refresh };
}

export default function CostBadge({ summary }: { summary: UsageSummary | null }) {
  const cost = summary ? `¥${summary.totalCostCny.toFixed(2)}` : "¥0.00";
  const used = summary?.rateLimit.used ?? 0;
  const limit = summary?.rateLimit.limit ?? 1;
  const nearLimit = used / Math.max(limit, 1) >= 0.8 || (summary?.rateLimit.limited ?? false);
  const title = summary
    ? `本会话：调用 ${summary.totalCalls} 次（失败 ${summary.failedCalls}）· 生成 ${used}/${limit} 次 · 缓存命中 ${Math.round(summary.cacheHitRate * 100)}% · 输入 ${summary.promptTokens} tok / 输出 ${summary.completionTokens} tok`
    : "费用数据加载中";
  return (
    <span
      className={`hidden rounded-lg border px-2 py-1 sm:inline-block ${
        nearLimit ? "border-amber-300 text-amber-600" : "border-stone-200 text-stone-500"
      }`}
      title={title}
    >
      {cost} · 本会话
    </span>
  );
}
