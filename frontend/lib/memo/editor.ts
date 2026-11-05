// メモエディタ（原文とリッチテキスト）が共通で公開する操作の型と、エディタ外から本文を差し替えるためのヘルパー。
// Shared handle type for the memo editors (source and rich text) and helpers that edit the document from outside the editor.

import type { EditorView } from "@codemirror/view";
import type { EditorState, TransactionSpec } from "@codemirror/state";

import type { MemoLineFormat, TextEdit } from "./list_editing";

// ツールバーから指定できる書式。行の書式に加えて、字下げと字上げ。
// Formats the toolbar can request: the line formats plus indent and outdent.
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

// ページ上のエージェントが、他のページで CodeMirror を読み込まなくてもメモのエディタへ入力できるよう、DOM 要素からエディタを引く対応表を持つ。
// The existing page agent can fill memo editors without loading CodeMirror on other pages.
export const memoEditorViews = new WeakMap<HTMLElement, MemoEditorHandle>();

// ツールバーによる変更も、タイピングと同じエディタの取り消し履歴に入る。
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

// 本文を差し替える。先頭と末尾の共通部分を除いた差分だけを書き換えるので、カーソルや取り消し履歴への影響が小さい。
// Replaces the document by rewriting only the changed middle after trimming the common prefix and suffix, which disturbs the caret and undo history less.
export function replaceMemoDocument(view: EditorView, next: string, userEvent: string) {
  const previous = view.state.doc.toString();
  if (previous === next) return;
  let from = 0;
  while (from < previous.length && from < next.length && previous[from] === next[from]) from++;
  let oldTo = previous.length, newTo = next.length;
  while (oldTo > from && newTo > from && previous[oldTo - 1] === next[newTo - 1]) { oldTo--; newTo--; }
  view.dispatch({ changes: { from, to: oldTo, insert: next.slice(from, newTo) }, userEvent });
}
