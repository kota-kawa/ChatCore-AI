/**
 * HTML エスケープ・テキスト整形ユーティリティ
 */

export function escapeHtml(value: unknown): string {
  const text = value === null || value === undefined ? "" : String(value);
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function formatMultilineHtml(value: unknown): string {
  return escapeHtml(value).replace(/\r\n|\r|\n/g, "<br>");
}
