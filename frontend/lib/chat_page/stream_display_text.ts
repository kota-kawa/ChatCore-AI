// ストリーミング本文の表示位置を、引用チップHTMLの途中で切らないよう整える。
// Keeps the revealed position of streamed text from slicing through citation-chip HTML.

const COMPLETE_WEB_SEARCH_CITATION =
  /<a\b[^>]*class\s*=\s*(["'])[^"']*\bweb-search-citation\b[^"']*\1[^>]*>[\s\S]*?<\/a>/gi;
const WEB_SEARCH_CITATION_START = /<a\b[^>]*class\s*=\s*(["'])[^"']*\bweb-search-citation\b/i;

// 引用チップHTMLを不可分な表示単位として扱う。表示位置が完成済みチップの途中なら
// 閉じタグ直後まで進め、不完全な末尾チップなら開始位置まで戻す。
// Treat citation-chip HTML as atomic. Advance through a complete chip instead
// of slicing its markup, or hold before an incomplete trailing chip.
export function normalizeCitationChipStreamBoundary(text: string, length: number): number {
  const boundedLength = Math.max(0, Math.min(length, text.length));
  COMPLETE_WEB_SEARCH_CITATION.lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = COMPLETE_WEB_SEARCH_CITATION.exec(text)) !== null) {
    const start = match.index;
    const end = COMPLETE_WEB_SEARCH_CITATION.lastIndex;
    if (boundedLength > start && boundedLength < end) return end;
  }

  const trailingText = text.slice(0, boundedLength);
  const possibleStart = trailingText.lastIndexOf("<a");
  if (possibleStart >= 0) {
    const possibleCitation = text.slice(possibleStart);
    if (WEB_SEARCH_CITATION_START.test(possibleCitation) && !possibleCitation.includes("</a>")) {
      return possibleStart;
    }
  }

  return boundedLength;
}
