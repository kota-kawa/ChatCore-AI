// 表示用文字列の置換に合わせて、元テキストとの位置対応を更新する。
// Updates source-position mappings alongside display-only text replacements.

export interface DisplaySourceSpan {
  start: number;
  end: number;
}

// 表示専用の置換に合わせて、任意の元ソース範囲も更新する。
// Update optional source spans alongside a display-only replacement.
export function replaceDisplayText(
  text: string, pattern: RegExp, replacement: string, positions?: DisplaySourceSpan[],
): string {
  if (!positions) return text.replace(pattern, replacement);
  const matches = Array.from(text.matchAll(pattern));
  for (const match of matches.reverse()) {
    const start = match.index;
    if (positions) {
      const span = { start: positions[start].start, end: positions[start + match[0].length - 1].end };
      positions.splice(start, match[0].length, ...Array.from(replacement, () => span));
    }
    text = text.slice(0, start) + replacement + text.slice(start + match[0].length);
  }
  return text;
}
