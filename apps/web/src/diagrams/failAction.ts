/** 沙箱失败处置策略（T2.2.3 → T2.3.2；评审 D2）。 */

/** 第 1 次失败修复重试，之后一律降级（修复产物可能还是同一坏组件）。 */
export function sandboxFailAction(failCount: number): "repair" | "degrade" {
  return failCount <= 1 ? "repair" : "degrade";
}
