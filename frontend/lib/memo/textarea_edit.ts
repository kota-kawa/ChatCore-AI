import type { TextEdit } from "./list_editing";

// ---------------------------------------------------------------------------
// Memo editor: apply a text edit to a textarea like a keystroke
// ---------------------------------------------------------------------------

// 編集を「入力」として反映する。値を直接書き換えるとブラウザの「元に戻す」履歴が消えるため、
// 履歴に積まれる execCommand を先に試し、使えない環境では setRangeText に落とす。
// どちらも input イベントが飛ぶので、React の onChange はそのまま働く。
// Applies the edit as typed input. Assigning the value directly would wipe the browser's undo
// history, so execCommand (which records history) goes first and setRangeText is the fallback.
// Both fire an input event, so React's onChange keeps working.
export function applyTextEdit(textarea: HTMLTextAreaElement, edit: TextEdit): void {
  textarea.focus({ preventScroll: true });
  if (edit.start !== edit.end || edit.text) {
    textarea.setSelectionRange(edit.start, edit.end);
    const command = edit.text ? "insertText" : "delete";
    const applied = typeof document.execCommand === "function" && document.execCommand(command, false, edit.text);
    if (!applied) {
      textarea.setRangeText(edit.text, edit.start, edit.end, "end");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    }
  }
  textarea.setSelectionRange(edit.selectionStart, edit.selectionEnd);
}

// 日本語変換の確定の Enter か。Safari は確定の keydown を変換終了の後に送るため isComposing が
// false になるが、keyCode は 229 のままなので、それも確定として扱う。
// Whether this Enter confirms an IME conversion. Safari sends that keydown after the composition
// has ended, so isComposing is false, but keyCode stays 229; treat that as a confirmation too.
export function isImeConfirmKey(event: { keyCode: number; nativeEvent: { isComposing: boolean } }): boolean {
  return event.nativeEvent.isComposing || event.keyCode === 229;
}
