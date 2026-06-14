/**
 * 文字列の日付をDateオブジェクトに変換する
 * Parse a date string into a Date object
 */
function parseDate(value?: string | null) {
  if (!value) return null;
  const parsed = new Date(value);
  // 無効な日付の場合はnullを返す
  // Return null if the date is invalid
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed;
}

/**
 * 日付と時刻を日本語フォーマットで文字列化する
 * Format a date and time as a Japanese formatted string
 */
export function formatDateTime(value?: string | null): string {
  const parsed = parseDate(value);
  if (!parsed) return "";
  return new Intl.DateTimeFormat("ja-JP", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parsed);
}

/**
 * 日付を日本語フォーマットで文字列化する
 * Format a date as a Japanese formatted string
 */
export function formatDate(value?: string | null): string {
  const parsed = parseDate(value);
  if (!parsed) return "";
  return new Intl.DateTimeFormat("ja-JP", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(parsed);
}
