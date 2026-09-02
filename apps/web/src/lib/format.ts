/** 展示用格式化工具。 */

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

export function parseStatusLabel(status: string): string {
  switch (status) {
    case "pending":
      return "排队中";
    case "parsing":
      return "解析中";
    case "success":
      return "可阅读";
    case "failed":
      return "解析失败";
    default:
      return status;
  }
}
