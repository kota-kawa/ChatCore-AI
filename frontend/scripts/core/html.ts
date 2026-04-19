/**
 * HTML エスケープ・テキスト整形ユーティリティ
 */

const SAFE_CLASS_PATTERNS = [
  /^hljs(?:-[a-z0-9_-]+)?$/i,
  /^language-[a-z0-9_-]+$/i,
  /^code-block-(?:container|header|lang|copy-btn)$/i,
  /^bi(?:-[a-z0-9_-]+)?$/i,
];

export function sanitizeClassAttributeValue(value: unknown): string {
  const classNames = value === null || value === undefined ? "" : String(value);
  const safeTokens = classNames
    .split(/\s+/)
    .map((token) => token.trim())
    .filter((token) => token.length > 0)
    .filter((token) => SAFE_CLASS_PATTERNS.some((pattern) => pattern.test(token)));

  return Array.from(new Set(safeTokens)).join(" ");
}

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
