// ストリーミング応答のうち、表示ペーシングの対象だけを切り出す。
// Web検索トレースは折りたたみUIとして先頭へ差し込まれる長いHTMLだが、画面上では
// 要約1行しか占めない。これを文字単位で排出すると本文の表示が長時間止まるため、
// 完成した先頭トレースは即時表示し、その後ろの回答本文だけをペーシングする。
// Separates the part of a streamed response that should be paced. A web-search
// trace is a large HTML block inserted before the answer but occupies only one
// collapsed summary line. Once complete, it is shown immediately while only
// the answer body behind it is paced.

export type StreamDisplayText = {
  instantPrefix: string;
  pacedText: string;
};

const LEADING_WEB_SEARCH_TRACE =
  /^(\s*)<details\b[^>]*class\s*=\s*(["'])[^"']*\bweb-search-sources\b[^"']*\2[^>]*>/i;
const DETAILS_TAG = /<\/?details\b[^>]*>/gi;

// ネストしたdetailsを深さで追跡し、先頭のWeb検索ブロックに対応する閉じタグを探す。
// Track nested details by depth to find the closing tag for the leading trace.
function findLeadingTraceEnd(text: string, rootStart: number) {
  DETAILS_TAG.lastIndex = rootStart;
  let depth = 0;
  let foundRoot = false;
  let match: RegExpExecArray | null;

  while ((match = DETAILS_TAG.exec(text)) !== null) {
    const isClosing = /^<\//.test(match[0]);
    if (!foundRoot) {
      if (isClosing || match.index !== rootStart) return null;
      foundRoot = true;
    }

    depth += isClosing ? -1 : 1;
    if (depth === 0) return DETAILS_TAG.lastIndex;
  }

  return null;
}

export function splitStreamDisplayText(text: string): StreamDisplayText {
  const leadingTrace = LEADING_WEB_SEARCH_TRACE.exec(text);
  if (!leadingTrace) return { instantPrefix: "", pacedText: text };

  const rootStart = leadingTrace[1].length;
  const traceEnd = findLeadingTraceEnd(text, rootStart);
  if (traceEnd === null) return { instantPrefix: "", pacedText: text };

  // トレース直後の改行も即時側へ含め、本文の先頭が空白の排出待ちにならないようにする。
  // Include whitespace after the trace so the body does not wait on invisible
  // characters before its first visible word.
  const trailingWhitespaceLength = text.slice(traceEnd).match(/^\s*/)?.[0].length ?? 0;
  const prefixEnd = traceEnd + trailingWhitespaceLength;
  return {
    instantPrefix: text.slice(0, prefixEnd),
    pacedText: text.slice(prefixEnd),
  };
}
