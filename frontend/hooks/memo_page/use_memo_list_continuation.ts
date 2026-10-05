import { useEffect } from "react";

import { continueListOnEnter } from "../../lib/memo/list_editing";
import { applyTextEdit } from "../../lib/memo/textarea_edit";

// メモ本文の textarea（data-memo-editor 付き）で改行したとき、リストの記号を引き継ぐ。
// 改行は beforeinput の insertLineBreak で拾う。スマホの画面キーボードは keydown の key を
// 正しく送らないことがあり、日本語変換の確定の Enter もこのイベントにはならないため。
// 入力欄は開閉で付け外しされ、詳細モーダルは body 直下へポータルされるので、メモ画面で
// 1 回だけ呼び、document で待ち受ける。
// Carries the list marker over when a line break is typed in a memo body textarea (marked with
// data-memo-editor). The break is caught as beforeinput/insertLineBreak: on-screen keyboards do
// not always send a usable keydown key, and the Enter that confirms an IME conversion never
// produces this event. The textareas mount and unmount and the detail modal is portalled under
// body, so the memo page calls this once and it listens on the document.
export function useMemoListContinuation() {
  useEffect(() => {
    const handleBeforeInput = (event: InputEvent) => {
      if (event.inputType !== "insertLineBreak" || event.isComposing) return;
      const textarea = event.target;
      if (!(textarea instanceof HTMLTextAreaElement) || textarea.dataset.memoEditor === undefined) return;
      const edit = continueListOnEnter(textarea.value, textarea.selectionStart, textarea.selectionEnd);
      if (!edit) return;
      event.preventDefault();
      applyTextEdit(textarea, edit);
    };
    document.addEventListener("beforeinput", handleBeforeInput);
    return () => document.removeEventListener("beforeinput", handleBeforeInput);
  }, []);
}
