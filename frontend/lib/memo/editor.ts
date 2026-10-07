import type { EditorView } from "@codemirror/view";

import type { TextEdit } from "./list_editing";

// The existing page agent can fill memo editors without loading CodeMirror on other pages.
export const memoEditorViews = new WeakMap<HTMLElement, EditorView>();

// Toolbar changes share the editor's undo history with typing.
export function applyMemoEditorEdit(view: EditorView, edit: TextEdit) {
  view.dispatch({
    changes: { from: edit.start, to: edit.end, insert: edit.text },
    selection: { anchor: edit.selectionStart, head: edit.selectionEnd },
    userEvent: "input",
    scrollIntoView: true,
  });
  view.focus();
}
