// メモエージェントの編集（部分置換 old_string → new_string、または全文置換）を扱う純関数。
// 部分置換の規則は services/memo_agent_actions.py の apply_memo_edits と同じで、
// ケース表 tests/fixtures/memo_agent_edit_cases.json を両方のテストが共有する。
// Pure helpers for memo agent edits (partial old_string -> new_string replacements, or a full replacement).
// The partial-edit rules mirror apply_memo_edits in services/memo_agent_actions.py, and both test suites
// share the case table in tests/fixtures/memo_agent_edit_cases.json.

// 1 回の部分置換で受け付ける編集の最大件数（サーバーの MEMO_EDIT_MAX_EDITS と揃える）
// Maximum number of edits in one partial replacement (keep in sync with MEMO_EDIT_MAX_EDITS on the server)
export const MEMO_AGENT_MAX_EDITS = 20;

// 編集後の本文の最大文字数。サーバー（Python の len）と同じくコードポイントで数える
// Maximum edited body length, counted in code points like the server (Python's len)
export const MEMO_AGENT_MAX_BODY_LENGTH = 60_000;

export type MemoTextEdit = { old_string: string; new_string: string };

// memo_edit ステップが適用する編集内容
// Edit payload a memo_edit step applies to the currently open memo
export type MemoEditPayload =
  | { kind: "content"; content: string; title?: string }
  | { kind: "edits"; edits: MemoTextEdit[]; title?: string };

export type MemoEditsFailure =
  | "no_edits"
  | "too_many_edits"
  | "empty_old_string"
  | "not_found"
  | "ambiguous"
  | "overlap"
  | "too_long";

export type MemoEditsResult = { ok: true; body: string } | { ok: false; failure: MemoEditsFailure };

export type MemoEditStepReadResult =
  | { ok: true; payload: MemoEditPayload }
  | { ok: false; reason: "empty" | "invalid" };

// 改行コードを LF へそろえる（CRLF と単独の CR の両方）
// Unify line breaks to LF, covering both CRLF and a lone CR
function normalizeLineBreaks(text: string): string {
  return text.replace(/\r\n?/g, "\n");
}

// サーバーの parse_memo_text と同じく、JSON 文字列として保存された本文だけを復号する。
// parseMemoText は文字列でない JSON を空文字にするため、LLM に見せた本文とずれないようここでは使わない。
// Decode only bodies stored as a JSON string, like parse_memo_text on the server. parseMemoText turns
// non-string JSON into "", which would diverge from the body the LLM saw, so it is not used here.
function decodeStoredMemoText(raw: string): string {
  if (!raw) return "";
  try {
    const parsed: unknown = JSON.parse(raw);
    return typeof parsed === "string" ? parsed : raw;
  } catch {
    return raw;
  }
}

// 照合の基準にする本文へそろえる（サーバーの normalize_memo_body と同じ規則）
// Normalize a memo body for matching (same rule as normalize_memo_body on the server)
function normalizeMemoBody(raw: string): string {
  return normalizeLineBreaks(decodeStoredMemoText(raw));
}

function countCodePoints(text: string): number {
  let count = 0;
  for (const _codePoint of text) count += 1;
  return count;
}

// 部分置換を本文へ原子的に適用する。全件適用できるときだけ新しい本文を返す。
// 位置はすべて元の本文上で決めるため、edits の並び順には依存しない。
// Apply partial edits to a memo body atomically: all of them or none. Every position is located in the
// original body, so the order of edits does not matter.
export function applyMemoEdits(body: string, edits: readonly MemoTextEdit[]): MemoEditsResult {
  if (!edits.length) return { ok: false, failure: "no_edits" };
  if (edits.length > MEMO_AGENT_MAX_EDITS) return { ok: false, failure: "too_many_edits" };

  const source = normalizeMemoBody(body);
  const spans: { start: number; end: number; replacement: string }[] = [];
  for (const edit of edits) {
    const oldString = normalizeLineBreaks(edit.old_string);
    if (!oldString) return { ok: false, failure: "empty_old_string" };
    const start = source.indexOf(oldString);
    if (start === -1) return { ok: false, failure: "not_found" };
    // 重なり合う出現も別の一致として数える（"aaa" の中の "aa" は 2 か所）
    // Overlapping occurrences count as separate matches ("aa" occurs twice in "aaa")
    if (source.indexOf(oldString, start + 1) !== -1) return { ok: false, failure: "ambiguous" };
    spans.push({ start, end: start + oldString.length, replacement: normalizeLineBreaks(edit.new_string) });
  }

  spans.sort((a, b) => a.start - b.start);
  let furthestEnd = -1;
  for (const span of spans) {
    if (span.start < furthestEnd) return { ok: false, failure: "overlap" };
    furthestEnd = Math.max(furthestEnd, span.end);
  }

  let edited = "";
  let cursor = 0;
  for (const span of spans) {
    edited += source.slice(cursor, span.start) + span.replacement;
    cursor = span.end;
  }
  edited += source.slice(cursor);
  if (countCodePoints(edited) > MEMO_AGENT_MAX_BODY_LENGTH) return { ok: false, failure: "too_long" };
  return { ok: true, body: edited };
}

function parseMemoTextEdits(value: unknown): MemoTextEdit[] | null {
  if (!Array.isArray(value) || !value.length) return null;
  const edits: MemoTextEdit[] = [];
  for (const item of value) {
    if (!item || typeof item !== "object") return null;
    const { old_string: oldString, new_string: newString } = item as Record<string, unknown>;
    if (typeof oldString !== "string" || typeof newString !== "string") return null;
    edits.push({ old_string: oldString, new_string: newString });
  }
  return edits;
}

// memo_edit ステップから編集内容を読み取る。edits と content はどちらか一方だけ（null は未指定。サーバーの検証と同じ）
// Read the edit payload of a memo_edit step: exactly one of edits or content (null counts as absent, as on the server)
export function readMemoEditStep(step: { content?: unknown; edits?: unknown; title?: unknown }): MemoEditStepReadResult {
  const hasContent = step.content !== undefined && step.content !== null;
  const hasEdits = step.edits !== undefined && step.edits !== null;
  if (hasContent === hasEdits) return { ok: false, reason: "invalid" };

  const title = typeof step.title === "string" && step.title.trim() ? step.title : undefined;
  if (hasEdits) {
    const edits = parseMemoTextEdits(step.edits);
    return edits ? { ok: true, payload: { kind: "edits", edits, title } } : { ok: false, reason: "invalid" };
  }
  if (typeof step.content !== "string" || !step.content.trim()) return { ok: false, reason: "empty" };
  return { ok: true, payload: { kind: "content", content: step.content, title } };
}
