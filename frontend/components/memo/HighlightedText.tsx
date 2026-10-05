import { useMemo } from "react";

import { buildHighlightPattern, HIGHLIGHT_CLASS, splitByPattern } from "../../lib/memo/search_highlight";

// 文字列の中の検索語に一致した部分を <mark> で強調する。検索語が無ければ文字列をそのまま出す
// Marks the parts of a string that match the search terms; renders the string untouched without a query
export function HighlightedText({ text, query }: { text: string; query: string }) {
  const pattern = useMemo(() => buildHighlightPattern(query), [query]);
  if (!pattern) return <>{text}</>;
  return (
    <>
      {splitByPattern(text, pattern).map((part, index) =>
        part.match ? <mark key={index} className={HIGHLIGHT_CLASS}>{part.text}</mark> : part.text,
      )}
    </>
  );
}
