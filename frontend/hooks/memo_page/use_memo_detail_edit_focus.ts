import { useCallback, useLayoutEffect, useRef } from "react";

import { alignTextareaToClick, type MemoEditPosition } from "../../lib/memo/detail_edit_position";

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
  const pendingTargetRef = useRef<{ target: MemoDetailEditTarget; position?: MemoEditPosition } | null>(null);

  const beginEditing = useCallback((target: MemoDetailEditTarget, position?: MemoEditPosition) => {
    pendingTargetRef.current = { target, position };
    setPreviewMode(false);
  }, [setPreviewMode]);

  useLayoutEffect(() => {
    if (previewMode) {
      pendingTargetRef.current = null;
      return;
    }
    const request = pendingTargetRef.current;
    if (!request) return;
    const { target, position } = request;
    pendingTargetRef.current = null;

    const element = target === "title" ? titleInputRef.current : textareaRef.current;
    if (!element) return;
    // クリックでは指定位置、Enter では従来どおり末尾から編集する。
    // Clicks retain their source position; Enter keeps the append shortcut.
    const offset = Math.min((position ? position.offset ?? 0 : element.value.length), element.value.length);
    element.focus({ preventScroll: true });
    element.setSelectionRange(offset, offset);
    if (element instanceof HTMLTextAreaElement) {
      if (position) alignTextareaToClick(element, position);
      else element.scrollTop = element.scrollHeight;
    }
  }, [previewMode]);

  return { textareaRef, titleInputRef, beginEditing };
}
