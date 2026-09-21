import { useCallback, useEffect, useRef } from "react";

// ---------------------------------------------------------------------------
// Memo detail: focus hand-off from the preview to the editor
// ---------------------------------------------------------------------------

export type MemoDetailEditTarget = "body" | "title";

interface UseMemoDetailEditFocusParams {
  previewMode: boolean;
  setPreviewMode: (previewMode: boolean) => void;
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
  const pendingTargetRef = useRef<MemoDetailEditTarget | null>(null);

  const beginEditing = useCallback((target: MemoDetailEditTarget) => {
    pendingTargetRef.current = target;
    setPreviewMode(false);
  }, [setPreviewMode]);

  useEffect(() => {
    if (previewMode) {
      pendingTargetRef.current = null;
      return;
    }
    const target = pendingTargetRef.current;
    if (!target) return;
    pendingTargetRef.current = null;

    const element = target === "title" ? titleInputRef.current : textareaRef.current;
    if (!element) return;
    // 追記が最も多い使い方なので、キャレットは末尾に置く
    // Appending is the most common edit, so the caret goes to the end
    const end = element.value.length;
    element.focus({ preventScroll: true });
    element.setSelectionRange(end, end);
    if (element instanceof HTMLTextAreaElement) {
      element.scrollTop = element.scrollHeight;
    }
  }, [previewMode]);

  return { textareaRef, titleInputRef, beginEditing };
}
