import { replaceDisplayText, type DisplaySourceSpan } from "../../scripts/chat/display_source_positions";
import { formatMathExpressionForDisplay, looksLikeLooseMathLine } from "../../scripts/chat/math_display";
import { maskWebSearchArtifacts } from "../../scripts/chat/memo_text";

function escapeMath(text: string, positions: DisplaySourceSpan[]) {
  const escapedPositions: DisplaySourceSpan[] = [];
  let escaped = "";
  for (let i = 0; i < text.length; i++) {
    if (/[\\`*_[\]<>]/.test(text[i])) {
      escaped += "\\";
      escapedPositions.push(positions[i]);
    }
    escaped += text[i];
    escapedPositions.push(positions[i]);
  }
  return { text: escaped, positions: escapedPositions };
}

function prepareMath(text: string, positions: DisplaySourceSpan[]) {
  const lines = text.split("\n");
  let cursor = 0;
  const mappedLines = lines.map((line) => {
    const spans = positions.slice(cursor, cursor + line.length);
    const newline = positions[cursor + line.length];
    cursor += line.length + 1;
    return { text: line, positions: spans, newline };
  });
  for (let i = 0; i < mappedLines.length; i++) {
    const line = mappedLines[i];
    if (/^\\?\[$/.test(line.text.trim())) {
      let end = i + 1;
      while (end < mappedLines.length && !/^\\?\]$/.test(mappedLines[end].text.trim())) end++;
      if (end < mappedLines.length && mappedLines.slice(i + 1, end).some((entry) => looksLikeLooseMathLine(entry.text))) {
        line.text = "";
        line.positions = [];
        for (let j = i + 1; j < end; j++) {
          const entry = mappedLines[j];
          Object.assign(entry, escapeMath(formatMathExpressionForDisplay(entry.text, entry.positions), entry.positions));
        }
        mappedLines[end].text = "";
        mappedLines[end].positions = [];
        i = end;
        continue;
      }
    }
    const matches = Array.from(line.text.matchAll(/\(([A-Za-z][A-Za-z0-9_{}^=+\-*/\\]+)\)/g));
    for (const match of matches.reverse()) {
      const expression = match[1];
      if (!/[_^=\\]/.test(expression) || expression.length > 32) continue;
      const spans = line.positions.slice(match.index + 1, match.index + match[0].length - 1);
      const replacement = escapeMath(formatMathExpressionForDisplay(expression, spans), spans);
      line.text = line.text.slice(0, match.index) + replacement.text + line.text.slice(match.index + match[0].length);
      line.positions.splice(match.index, match[0].length, ...replacement.positions);
    }
  }
  return {
    text: mappedLines.map((line) => line.text).join("\n"),
    positions: mappedLines.flatMap((line) => [...line.positions, ...(line.newline ? [line.newline] : [])]),
  };
}

export function prepareMemoPreviewSource(source: string) {
  let text = source;
  let positions: DisplaySourceSpan[] = Array.from({ length: source.length }, (_, i) => ({ start: i, end: i + 1 }));
  try {
    const parsed: unknown = JSON.parse(source);
    if (typeof parsed === "string") {
      const spans: DisplaySourceSpan[] = [];
      const start = source.indexOf('"') + 1;
      const end = source.lastIndexOf('"');
      for (let i = start; i < end; i++) {
        const escape = source[i] === "\\" ? source.slice(i).match(/^\\(?:u[\da-f]{4}|.)/i)?.[0] : null;
        spans.push({ start: i, end: i + (escape?.length ?? 1) });
        i += (escape?.length ?? 1) - 1;
      }
      text = parsed;
      positions = spans;
    }
  } catch { /* Plain Markdown is the usual representation. */ }
  text = maskWebSearchArtifacts(text);
  text = replaceDisplayText(text, /\r\n?/g, "\n", positions);
  let cursor = 0;
  const segments = text.split(/(```[\s\S]*?```|```[\s\S]*$)/).map((segment, index) => {
    const spans = positions.slice(cursor, cursor + segment.length);
    cursor += segment.length;
    if (index % 2 === 1) return { text: segment, positions: spans };
    segment = replaceDisplayText(segment, /[\u200B-\u200D\u2060\uFEFF]/g, "", spans);
    segment = replaceDisplayText(segment, /\u00a0/g, " ", spans);
    return prepareMath(segment, spans);
  });
  return { text: segments.map((segment) => segment.text).join(""), positions: segments.flatMap((segment) => segment.positions) };
}
