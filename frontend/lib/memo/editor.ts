import type { EditorView } from "@codemirror/view";
import type { EditorState, TransactionSpec } from "@codemirror/state";

import type { MemoLineFormat, TextEdit } from "./list_editing";

export type MemoFormat = MemoLineFormat | "indent" | "outdent";

// 原文とリッチテキストの両方が、同じ本文・履歴とページ側の操作契約を使う。
// Rich text and source editing share the document, history, and page-facing operations.
export interface MemoEditorHandle {
  readonly state: EditorState;
  readonly contentDOM: HTMLElement;
  dispatch(spec: TransactionSpec): void;
  focus(): void;
  undo(): boolean;
  redo(): boolean;
  format(format: MemoFormat): void;
}

// The existing page agent can fill memo editors without loading CodeMirror on other pages.
export const memoEditorViews = new WeakMap<HTMLElement, MemoEditorHandle>();

// Toolbar changes share the editor's undo history with typing.
export function applyMemoEditorEdit(view: Pick<MemoEditorHandle, "dispatch" | "focus">, edit: TextEdit) {
  view.dispatch({
    changes: { from: edit.start, to: edit.end, insert: edit.text },
    selection: { anchor: edit.selectionStart, head: edit.selectionEnd },
    userEvent: "input",
    scrollIntoView: true,
  });
  view.focus();
}

export function replaceMemoDocument(view: EditorView, next: string, userEvent: string) {
  const previous = view.state.doc.toString();
  if (previous === next) return;
  let from = 0;
  while (from < previous.length && from < next.length && previous[from] === next[from]) from++;
  let oldTo = previous.length, newTo = next.length;
  while (oldTo > from && newTo > from && previous[oldTo - 1] === next[newTo - 1]) { oldTo--; newTo--; }
  view.dispatch({ changes: { from, to: oldTo, insert: next.slice(from, newTo) }, userEvent });
}
