import type { MouseEvent, RefObject } from "react";
import type { EditorView } from "@codemirror/view";

import { useTranslation } from "../../contexts/locale_context";
import type { MessageKey } from "../../lib/i18n/catalogs/ja";
import { indentLines, toggleLineFormat, type MemoLineFormat, type TextEdit } from "../../lib/memo/list_editing";
import { applyMemoEditorEdit } from "../../lib/memo/editor";

// ── Memo body formatting toolbar ──
// 記号を手で打たずに、カーソルのある行（選択中の行）へリストや見出しを付け外しする。
// 押してもキーボードが閉じないよう、ボタンはフォーカスを奪わない。
// Adds or removes list / heading markers on the caret line (or the selected lines) without typing
// the symbols. The buttons never take focus, so the on-screen keyboard stays open.
type FormatAction = {
  labelKey: MessageKey;
  icon: string;
  edit: (value: string, start: number, end: number) => TextEdit | null;
};

const lineFormat = (format: MemoLineFormat) => (value: string, start: number, end: number) =>
  toggleLineFormat(value, start, end, format);

const FORMAT_ACTIONS: FormatAction[] = [
  { labelKey: "memo.format.task", icon: "bi-check2-square", edit: lineFormat("task") },
  { labelKey: "memo.format.bullet", icon: "bi-list-ul", edit: lineFormat("bullet") },
  { labelKey: "memo.format.number", icon: "bi-list-ol", edit: lineFormat("number") },
  { labelKey: "memo.format.heading", icon: "bi-type-h2", edit: lineFormat("heading") },
  { labelKey: "memo.format.outdent", icon: "bi-text-indent-right", edit: (value, start, end) => indentLines(value, start, end, -1) },
  { labelKey: "memo.format.indent", icon: "bi-text-indent-left", edit: (value, start, end) => indentLines(value, start, end, 1) },
];

const keepEditorFocus = (event: MouseEvent) => event.preventDefault();

export function MemoFormatToolbar({ editorRef }: { editorRef: RefObject<EditorView | null> }) {
  const { t } = useTranslation();
  const run = (action: FormatAction) => {
    const editor = editorRef.current;
    if (!editor) return;
    const { from, to } = editor.state.selection.main;
    const edit = action.edit(editor.state.doc.toString(), from, to);
    if (edit) applyMemoEditorEdit(editor, edit);
    else editor.focus();
  };
  return (
    <div className="memo-format-toolbar" role="toolbar" aria-label={t("memo.format.toolbar")}>
      {FORMAT_ACTIONS.map((action) => (
        <button
          key={action.labelKey}
          type="button"
          className="memo-format-toolbar__btn"
          onMouseDown={keepEditorFocus}
          onClick={() => run(action)}
          aria-label={t(action.labelKey)}
          data-tooltip={t(action.labelKey)}
          data-tooltip-placement="top"
        >
          <i className={`bi ${action.icon}`} aria-hidden="true"></i>
        </button>
      ))}
    </div>
  );
}
