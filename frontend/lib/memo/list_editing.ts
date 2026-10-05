// ---------------------------------------------------------------------------
// Memo editor: Markdown list editing on a plain textarea
// ---------------------------------------------------------------------------

// メモ本文は Markdown のテキストなので、リストの続きやチェックの切り替えは
// 「どの範囲をどの文字列に置き換え、カーソルをどこへ置くか」という編集として表す。
// ここは文字列だけを扱い、textarea への反映は lib/memo/textarea_edit.ts が行う。
// A memo body is Markdown text, so continuing a list or ticking a checkbox is expressed as
// "replace this range with this text and put the caret here". This module only handles strings;
// lib/memo/textarea_edit.ts applies the result to a textarea.

export interface TextEdit {
  start: number;
  end: number;
  text: string;
  selectionStart: number;
  selectionEnd: number;
}

export type MemoLineFormat = "task" | "bullet" | "number" | "heading";

// 行頭の字下げ・引用記号と、その後ろのリスト記号（チェック欄を含む）
// Leading indent / quote markers, then the list marker (with its checkbox, if any)
const LIST_LINE = /^(\s*(?:>\s?)*)(?:([-*+])|(\d{1,9})([.)]))(\s+)(?:\[([ xX])\](\s+))?/;
const HEADING_LINE = /^(\s*)(#{1,6})\s+/;
const FENCE_LINE = /^\s*(```|~~~)/;
const INDENT = "  ";

function lineBounds(value: string, position: number) {
  const start = value.lastIndexOf("\n", position - 1) + 1;
  const nextBreak = value.indexOf("\n", position);
  return { start, end: nextBreak < 0 ? value.length : nextBreak };
}

// Enter でリストを続ける。記号だけの行で Enter したらリストを抜ける（記号を消す）。
// リストの行でなければ null を返し、ブラウザ既定の改行に任せる。
// Continue a list on Enter. Enter on a line that holds only the marker leaves the list (the marker
// is removed). Returns null outside a list so the browser inserts its normal line break.
export function continueListOnEnter(value: string, selectionStart: number, selectionEnd: number): TextEdit | null {
  if (selectionStart !== selectionEnd) return null;
  const { start, end } = lineBounds(value, selectionStart);
  const line = value.slice(start, end);
  const match = line.match(LIST_LINE);
  if (!match) return null;
  // 記号の途中にカーソルがあるときは分割しない
  // Do not split the marker itself
  if (selectionStart - start < match[0].length) return null;

  if (!line.slice(match[0].length).trim()) {
    const indent = match[1];
    // 字下げした項目なら 1 段戻して続ける。一番外側なら記号を消してリストを抜ける
    // A nested item moves out one level and stays a list item; a top-level one drops its marker
    if (indent.endsWith(INDENT)) {
      const text = line.slice(INDENT.length);
      return { start, end, text, selectionStart: start + text.length, selectionEnd: start + text.length };
    }
    return { start, end, text: indent, selectionStart: start + indent.length, selectionEnd: start + indent.length };
  }

  const [, indent, bullet, number, delimiter, gap, checkbox, checkboxGap] = match;
  const marker = bullet ?? `${Number(number) + 1}${delimiter}`;
  const next = `\n${indent}${marker}${gap}${checkbox === undefined ? "" : `[ ]${checkboxGap}`}`;
  const caret = selectionStart + next.length;
  return { start: selectionStart, end: selectionStart, text: next, selectionStart: caret, selectionEnd: caret };
}

function selectedLineRange(value: string, selectionStart: number, selectionEnd: number) {
  const start = lineBounds(value, selectionStart).start;
  // 選択が行頭で終わっているときは、その行を含めない
  // A selection ending at the start of a line does not include that line
  const lastPosition = selectionEnd > selectionStart && value[selectionEnd - 1] === "\n" ? selectionEnd - 1 : selectionEnd;
  return { start, end: lineBounds(value, lastPosition).end };
}

function stripLineFormat(line: string) {
  const heading = line.match(HEADING_LINE);
  if (heading) return { indent: heading[1], body: line.slice(heading[0].length) };
  const list = line.match(LIST_LINE);
  if (list) return { indent: list[1], body: line.slice(list[0].length) };
  const indent = line.match(/^\s*/)?.[0] ?? "";
  return { indent, body: line.slice(indent.length) };
}

function lineHasFormat(line: string, format: MemoLineFormat) {
  if (format === "heading") return HEADING_LINE.test(line);
  const match = line.match(LIST_LINE);
  if (!match) return false;
  const isTask = match[6] !== undefined;
  if (format === "task") return isTask;
  if (format === "bullet") return match[2] !== undefined && !isTask;
  return match[3] !== undefined && !isTask;
}

// 選択中の行を指定の書式にそろえる。すでに全行がその書式なら外す。
// Give the selected lines the requested format, or remove it when every line already has it.
export function toggleLineFormat(
  value: string,
  selectionStart: number,
  selectionEnd: number,
  format: MemoLineFormat,
): TextEdit {
  const range = selectedLineRange(value, selectionStart, selectionEnd);
  const lines = value.slice(range.start, range.end).split("\n");
  const targets = lines.length > 1 ? lines.filter((line) => line.trim()) : lines;
  const remove = targets.length > 0 && targets.every((line) => lineHasFormat(line, format));

  let ordinal = 0;
  const nextLines = lines.map((line) => {
    if (lines.length > 1 && !line.trim()) return line;
    const { indent, body } = stripLineFormat(line);
    if (remove) return `${indent}${body}`;
    ordinal += 1;
    const prefix = format === "task" ? "- [ ] " : format === "bullet" ? "- " : format === "number" ? `${ordinal}. ` : "## ";
    return `${indent}${prefix}${body}`;
  });
  const text = nextLines.join("\n");

  if (lines.length === 1) {
    // 1 行だけなら、本文中のカーソル位置を保つ（記号の中にあった場合は本文の先頭へ）
    // For a single line keep the caret within the text (or move it to the start of the text)
    const oldPrefix = lines[0].length - stripLineFormat(lines[0]).body.length;
    const newPrefix = text.length - stripLineFormat(text).body.length;
    const shift = (position: number) => range.start + newPrefix + Math.max(0, position - range.start - oldPrefix);
    return { ...range, text, selectionStart: shift(selectionStart), selectionEnd: shift(selectionEnd) };
  }
  return { ...range, text, selectionStart: range.start, selectionEnd: range.start + text.length };
}

// 選択中の行を 1 段だけ字下げする／戻す
// Indent or outdent the selected lines by one level
export function indentLines(value: string, selectionStart: number, selectionEnd: number, direction: 1 | -1): TextEdit | null {
  const range = selectedLineRange(value, selectionStart, selectionEnd);
  const lines = value.slice(range.start, range.end).split("\n");
  const deltas: number[] = [];
  const nextLines = lines.map((line) => {
    if (direction === 1) {
      deltas.push(INDENT.length);
      return `${INDENT}${line}`;
    }
    const removable = line.startsWith(INDENT) ? INDENT.length : line.startsWith(" ") || line.startsWith("\t") ? 1 : 0;
    deltas.push(-removable);
    return line.slice(removable);
  });
  if (deltas.every((delta) => delta === 0)) return null;
  const text = nextLines.join("\n");
  if (lines.length === 1) {
    const shift = (position: number) => Math.max(range.start, position + deltas[0]);
    return { ...range, text, selectionStart: shift(selectionStart), selectionEnd: shift(selectionEnd) };
  }
  return { ...range, text, selectionStart: range.start, selectionEnd: range.start + text.length };
}

// 本文中のチェック欄（`[ ]` / `[x]`）の位置を、プレビューに並ぶ順で返す。コードブロックの中は数えない。
// Offsets of the checkbox markers (`[ ]` / `[x]`) in preview order; fenced code blocks are skipped.
export function findTaskMarkers(source: string): { offset: number; checked: boolean }[] {
  const markers: { offset: number; checked: boolean }[] = [];
  let fence: string | null = null;
  let offset = 0;
  for (const line of source.split("\n")) {
    const fenceMatch = line.match(FENCE_LINE);
    if (fenceMatch) {
      if (fence === null) fence = fenceMatch[1];
      else if (fence === fenceMatch[1]) fence = null;
    } else if (fence === null) {
      const match = line.match(LIST_LINE);
      if (match && match[6] !== undefined) {
        const markerOffset = offset + match[0].length - (match[7] ?? "").length - 3;
        markers.push({ offset: markerOffset, checked: match[6] !== " " });
      }
    }
    offset += line.length + 1;
  }
  return markers;
}

// プレビューで index 番目に並ぶチェック欄を切り替えた本文を返す。
// 描画されたチェック欄の数（renderedCount）と本文から数えた数が合わないときは、
// 別の行を書き換えるおそれがあるので何もしない（null）。
// Returns the body with the index-th checkbox of the preview toggled. When the number of rendered
// checkboxes differs from the number found in the source, the wrong line could be rewritten, so
// nothing is changed (null).
export function toggleTaskMarker(source: string, index: number, renderedCount: number): string | null {
  const markers = findTaskMarkers(source);
  if (markers.length !== renderedCount) return null;
  const marker = markers[index];
  if (!marker) return null;
  return `${source.slice(0, marker.offset)}[${marker.checked ? " " : "x"}]${source.slice(marker.offset + 3)}`;
}
