// ---------------------------------------------------------------------------
// Memo detail: click-to-edit guards
// ---------------------------------------------------------------------------

// プレビュー面のクリックのうち「編集に入る」意図と見なせるものだけを通す。
// リンクや操作部品のクリックはそのまま通常の動作に任せ、テキストをドラッグ選択した直後の
// クリック（コピー目的）も編集には切り替えない。
// Lets through only the preview-pane clicks that read as "start editing". Clicks on links or
// controls keep their normal behaviour, and a click that ends a drag selection (copying) does
// not switch modes either.
const INTERACTIVE_SELECTOR = "a, button, input, textarea, select, summary, [contenteditable=''], [contenteditable='true']";

export interface ClickToEditContext {
  target: EventTarget | null;
  defaultPrevented: boolean;
  selectionCollapsed: boolean;
}

export function shouldBeginEditingFromClick({ target, defaultPrevented, selectionCollapsed }: ClickToEditContext): boolean {
  if (defaultPrevented) return false;
  if (!selectionCollapsed) return false;
  const element = target as { closest?: (selector: string) => Element | null } | null;
  if (element && typeof element.closest === "function" && element.closest(INTERACTIVE_SELECTOR)) return false;
  return true;
}

// 現在の選択範囲が「点」かどうか。選択APIが無い環境では点として扱う。
// Whether the current selection is collapsed; environments without the API count as collapsed.
export function isSelectionCollapsed(doc: Document = document): boolean {
  const selection = doc.getSelection?.();
  if (!selection) return true;
  return selection.isCollapsed || selection.toString().length === 0;
}
