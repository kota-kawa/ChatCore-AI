// ---------------------------------------------------------------------------
// Memo editor: Markdown list edits
// ---------------------------------------------------------------------------

// メモ本文は Markdown のテキストなので、リストの続きやチェックの切り替えは
// 「どの範囲をどの文字列に置き換え、カーソルをどこへ置くか」という編集として表す。
// ここは文字列だけを扱い、エディタへの反映は lib/memo/editor.ts が行う。
// A memo body is Markdown text, so continuing a list or ticking a checkbox is expressed as
// "replace this range with this text and put the caret here". This module only handles strings;
// lib/memo/editor.ts applies the result to the editor.

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

// lineStart より前で、indent より浅いリスト行の字下げを返す（無ければ null）
// The indent of the nearest list line above lineStart that is shallower than indent, or null
function outerListIndent(value: string, lineStart: number, indent: string): string | null {
  const above = value.slice(0, Math.max(0, lineStart - 1)).split("\n");
  for (let i = above.length - 1; i >= 0; i--) {
    const match = above[i].match(LIST_LINE);
    if (!match) {
      if (above[i].trim()) return null;
      continue;
    }
    if (match[1].length < indent.length) return match[1];
  }
  return null;
}

// Markdown は「親の記号の幅」だけ字下げした行を入れ子として扱う（"- " は 2、"1. " は 3、"10. " は 4）。
// 上の行がリストならその幅、そうでなければ 2 を 1 段とする。
// Markdown nests a line indented by the width of its parent's marker ("- " is 2, "1. " is 3,
// "10. " is 4). One level is that width when the line above is a list item, otherwise 2.
function indentUnit(value: string, lineStart: number): string {
  if (lineStart === 0) return INDENT;
  const above = value.slice(0, lineStart - 1);
  const match = above.slice(above.lastIndexOf("\n") + 1).match(LIST_LINE);
  if (!match) return INDENT;
  const markerWidth = (match[2] ?? `${match[3]}${match[4]}`).length + 1;
  return " ".repeat(markerWidth);
}

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
    // 字下げした項目なら親の段まで戻して続ける。一番外側なら記号を消してリストを抜ける
    // A nested item moves out to its parent's level and stays a list item; a top-level one drops its marker
    const outer = outerListIndent(value, start, indent);
    if (outer !== null) {
      const text = outer + line.slice(indent.length);
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

// 選択中の行を 1 段だけ字下げする／戻す（複数行を選んでいるときの空行はそのまま）
// Indent or outdent the selected lines by one level (blank lines in a multi-line selection stay as they are)
export function indentLines(value: string, selectionStart: number, selectionEnd: number, direction: 1 | -1): TextEdit | null {
  const range = selectedLineRange(value, selectionStart, selectionEnd);
  const lines = value.slice(range.start, range.end).split("\n");
  const unit = indentUnit(value, range.start);
  const deltas: number[] = [];
  const nextLines = lines.map((line) => {
    if (lines.length > 1 && !line.trim()) {
      deltas.push(0);
      return line;
    }
    if (direction === 1) {
      deltas.push(unit.length);
      return `${unit}${line}`;
    }
    const leading = line.match(/^[ \t]*/)?.[0].length ?? 0;
    const removable = Math.min(leading, unit.length);
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

export interface TaskMarker {
  offset: number;
  checked: boolean;
  // 欄の後ろに続く、その行の文字 / The text that follows the checkbox on its line
  text: string;
}

// 本文中のチェック欄（`[ ]` / `[x]`）の位置を、プレビューに並ぶ順で返す。行頭のコードフェンスの
// 中と、欄の後ろに文字が無い行（描画では欄にならない）は数えない。描画との対応はこの数え方
// だけでは保証できないので、書き換える前に必ず matchRenderedTasks で照合する。
// Offsets of the checkbox markers (`[ ]` / `[x]`) in preview order. Lines inside a fenced code
// block and lines with nothing after the box (not rendered as a checkbox) are skipped. This count
// alone does not guarantee the mapping to the rendered boxes; matchRenderedTasks must confirm it
// before anything is rewritten.
export function findTaskMarkers(source: string): TaskMarker[] {
  const markers: TaskMarker[] = [];
  let fence: string | null = null;
  let offset = 0;
  for (const rawLine of source.split("\n")) {
    const line = rawLine.replace(/\r$/, "");
    const fenceMatch = line.match(FENCE_LINE);
    if (fenceMatch) {
      if (fence === null) fence = fenceMatch[1];
      else if (fence === fenceMatch[1]) fence = null;
    } else if (fence === null) {
      const match = line.match(LIST_LINE);
      const text = match && match[6] !== undefined ? line.slice(match[0].length).trim() : "";
      if (match && text) {
        const markerOffset = offset + match[0].length - (match[7] ?? "").length - 3;
        markers.push({ offset: markerOffset, checked: match[6] !== " ", text });
      }
    }
    offset += rawLine.length + 1;
  }
  return markers;
}

// 記号や空白を除いた文字だけにする。描画は Markdown の記号を落とすだけなので、描画された文字は
// 元の行の文字を順に拾ったものになる（リンク先の URL などは描画側に出ない）。
// Keeps letters and digits only. Rendering merely drops Markdown syntax, so the rendered
// characters are a subsequence of the source line's (link URLs and the like never render).
function comparableCharacters(text: string): string[] {
  return Array.from(text.normalize("NFKC").toLowerCase()).filter((character) => /[\p{L}\p{N}]/u.test(character));
}

function isSubsequence(needle: string[], haystack: string[]): boolean {
  let position = 0;
  for (const character of haystack) {
    if (position < needle.length && character === needle[position]) position += 1;
  }
  return position === needle.length;
}

// 描画されたチェック欄（先頭から順の、各行の表示文字とチェック状態）が、本文の欄の先頭と
// 1 つずつ対応していれば、その本文側の欄を返す。件数・状態・文字のどれかが合わなければ null。
// 一覧のカードは本文の先頭しか描画しないので、描画側が少ないのは許す（allowPrefix）。
// Returns the source markers when the rendered checkboxes (label and state, in order) line up
// one by one with the head of the source's. Any difference in count, state or text gives null.
// A list card renders only the head of the body, so fewer rendered boxes are allowed there
// (allowPrefix).
export interface RenderedTask {
  label: string;
  checked: boolean;
}

export function matchRenderedTasks(source: string, rendered: RenderedTask[], allowPrefix = false): TaskMarker[] | null {
  const markers = findTaskMarkers(source);
  if (allowPrefix ? markers.length < rendered.length : markers.length !== rendered.length) return null;
  const matches = rendered.every((task, index) => {
    const marker = markers[index];
    if (marker.checked !== task.checked) return false;
    const label = comparableCharacters(task.label);
    return label.length > 0 && isSubsequence(label, comparableCharacters(marker.text));
  });
  return matches ? markers : null;
}

// index 番目のチェック欄を切り替えた本文を返す。描画と本文が対応しなければ、別の行を
// 書き換えるおそれがあるので何もしない（null）。
// Returns the body with the index-th checkbox toggled. When the rendered boxes do not line up
// with the source, the wrong line could be rewritten, so nothing is changed (null).
export function toggleTaskMarker(source: string, index: number, rendered: RenderedTask[], allowPrefix = false): string | null {
  const marker = matchRenderedTasks(source, rendered, allowPrefix)?.[index];
  if (!marker) return null;
  return `${source.slice(0, marker.offset)}[${marker.checked ? " " : "x"}]${source.slice(marker.offset + 3)}`;
}
