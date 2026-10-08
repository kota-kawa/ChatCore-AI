import type { MouseEvent, RefObject } from "react";
import type { MemoEditorHandle, MemoFormat } from "../../lib/memo/editor";

import { useTranslation } from "../../contexts/locale_context";
import type { MessageKey } from "../../lib/i18n/catalogs/ja";

// ── Memo body formatting toolbar ──
// 記号を手で打たずに、選択した段落へリストや見出しを付け外しする（原文では行単位）。
// 押してもキーボードが閉じないよう、ボタンはフォーカスを奪わない。
// Formats selected rich-text blocks, or lines in source mode, without typing Markdown symbols.
// The buttons never take focus, so the on-screen keyboard stays open.
type FormatAction = {
  labelKey: MessageKey;
  icon: string;
  format: MemoFormat;
};

const FORMAT_ACTIONS: FormatAction[] = [
  { labelKey: "memo.format.task", icon: "bi-check2-square", format: "task" },
  { labelKey: "memo.format.bullet", icon: "bi-list-ul", format: "bullet" },
  { labelKey: "memo.format.number", icon: "bi-list-ol", format: "number" },
  { labelKey: "memo.format.heading", icon: "bi-type-h2", format: "heading" },
  { labelKey: "memo.format.outdent", icon: "bi-text-indent-right", format: "outdent" },
  { labelKey: "memo.format.indent", icon: "bi-text-indent-left", format: "indent" },
];

const keepEditorFocus = (event: MouseEvent) => event.preventDefault();

export function MemoFormatToggle({ open, onToggle, toolbarId, className = "" }: {
  open: boolean;
  onToggle: () => void;
  toolbarId: string;
  className?: string;
}) {
  const { t } = useTranslation();
  return (
    <button
      type="button"
      className={`memo-format-toggle ${className}`}
      aria-expanded={open}
      aria-controls={toolbarId}
      onMouseDown={keepEditorFocus}
      onClick={onToggle}
    >
      {t("memo.format.toolbar")}
    </button>
  );
}

export function MemoFormatToolbar({ editorRef, id, hidden = false }: {
  editorRef: RefObject<MemoEditorHandle | null>;
  id?: string;
  hidden?: boolean;
}) {
  const { t } = useTranslation();
  const run = (action: FormatAction) => {
    const editor = editorRef.current;
    if (!editor) return;
    editor.format(action.format);
  };
  return (
    <div id={id} hidden={hidden} className="memo-format-toolbar" role="toolbar" aria-label={t("memo.format.toolbar")}>
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
