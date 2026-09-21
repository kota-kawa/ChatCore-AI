import { useCallback, useEffect, useRef } from "react";

import { measureCaretTop } from "../../lib/memo/detail_click_to_edit";

// ---------------------------------------------------------------------------
// Memo detail: focus hand-off from the preview to the editor
// ---------------------------------------------------------------------------

export type MemoDetailEditTarget = "body" | "title";

// クリックで編集に入るときの手がかり。offset は原文中のキャレット位置、viewportY は
// クリックした行が面の上端から何 px 下に見えていたか。
// Anchor for a click-to-edit: `offset` is the caret position in the source and `viewportY`
// how far below the pane's top edge the clicked line was showing.
export interface MemoDetailEditAnchor {
  offset: number;
  viewportY: number;
}

interface UseMemoDetailEditFocusParams {
  previewMode: boolean;
  setPreviewMode: (previewMode: boolean) => void;
}

interface PendingEdit {
  target: MemoDetailEditTarget;
  anchor: MemoDetailEditAnchor | null;
}

// プレビュー面（本文・タイトル）をクリックしたら編集モードへ切り替え、描画された入力へ
// フォーカスを渡す。textarea は編集モードになってから初めてマウントされるので、要求を
// ref に控えておき、モードが切り替わった後の effect で実際にフォーカスする。
// Switches to edit mode when the preview (body or title) is clicked and hands focus to the
// input once it exists. The textarea mounts only in edit mode, so the request is parked in a
// ref and honoured by the effect that runs after the mode flips.
export function useMemoDetailEditFocus({ previewMode, setPreviewMode }: UseMemoDetailEditFocusParams) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const titleInputRef = useRef<HTMLInputElement>(null);
  const pendingRef = useRef<PendingEdit | null>(null);

  const beginEditing = useCallback((target: MemoDetailEditTarget, anchor: MemoDetailEditAnchor | null = null) => {
    pendingRef.current = { target, anchor };
    setPreviewMode(false);
  }, [setPreviewMode]);

  useEffect(() => {
    if (previewMode) {
      pendingRef.current = null;
      return;
    }
    const pending = pendingRef.current;
    if (!pending) return;
    pendingRef.current = null;

    if (pending.target === "title") {
      const input = titleInputRef.current;
      if (!input) return;
      const end = input.value.length;
      input.focus({ preventScroll: true });
      input.setSelectionRange(end, end);
      return;
    }

    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.focus({ preventScroll: true });

    if (!pending.anchor) {
      // キーボードなど位置の手がかりが無いときは末尾へ（追記が最も多い使い方）
      // Without a position (keyboard), go to the end: appending is the most common edit
      const end = textarea.value.length;
      textarea.setSelectionRange(end, end);
      textarea.scrollTop = textarea.scrollHeight;
      return;
    }

    // クリックした文字にキャレットを置き、その行が同じ高さに見えるようスクロールをそろえる。
    // 面が切り替わっても「見ていた場所」が動かないことが狙い。
    // Put the caret on the clicked character and scroll so that line sits at the same height:
    // the spot the user was looking at must not move when the surface changes.
    const offset = Math.min(Math.max(pending.anchor.offset, 0), textarea.value.length);
    textarea.setSelectionRange(offset, offset);
    const caretTop = measureCaretTop(textarea, offset);
    textarea.scrollTop = Math.max(0, caretTop - pending.anchor.viewportY);
  }, [previewMode]);

  return { textareaRef, titleInputRef, beginEditing };
}
