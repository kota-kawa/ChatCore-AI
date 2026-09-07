// サニタイズ済みMarkdownHTMLの見出しレベルをまとめて下げるユーティリティ。
// 投稿本文の h1/h2 がページ側の見出し階層（h1=ページタイトル, h2=セクション）と衝突するのを防ぐ。
// Utility that shifts every heading level inside already-sanitized Markdown HTML.
// It stops a post body's h1/h2 from colliding with the page's own hierarchy (h1 = page title, h2 = section).

// HTMLで表現できる最も深い見出しレベル / Deepest heading level HTML can express
const MAX_HEADING_LEVEL = 6;

// 開始タグと終了タグの両方を拾う（属性はそのまま保持する）
// Matches both the opening and closing tag, preserving any attributes
const HEADING_TAG_PATTERN = /<(\/?)h([1-6])(\s[^>]*)?>/gi;

/**
 * サニタイズ済みHTML内の見出しをoffset段だけ深くする（h6が上限）。
 * 本文はサニタイズ済みなので、コードブロック内の見出しはエスケープ済みで影響を受けない。
 *
 * Shift every heading in sanitized HTML `offset` levels deeper (capped at h6).
 * The input is already sanitized, so headings inside code blocks stay escaped and untouched.
 */
export function demoteMarkdownHeadings(html: string, offset: number): string {
  if (!html || !Number.isFinite(offset) || offset <= 0) return html;
  const shift = Math.floor(offset);
  return html.replace(HEADING_TAG_PATTERN, (_match, slash: string, level: string, attrs?: string) => {
    const demoted = Math.min(Number(level) + shift, MAX_HEADING_LEVEL);
    return `<${slash}h${demoted}${attrs || ""}>`;
  });
}
