import { useCallback, useLayoutEffect, useRef } from "react";

import { alignTextareaToClick, type MemoEditPosition } from "../../lib/memo/detail_edit_position";

// ---------------------------------------------------------------------------
// Memo detail: focus hand-off from the preview to the editor
// ---------------------------------------------------------------------------

export type MemoDetailEditTarget = "body" | "title";

interface UseMemoDetailEditFocusParams {
  previewMode: boolean;
  setPreviewMode: (previewMode: boolean) => void;
  // 編集中の本文。クリック位置は、この文字列に対する位置として渡ってくる
  // The body being edited; click positions arrive as offsets into this string
  bodySource: string;
}

// プレビュー面（本文・タイトル）をクリックしたら編集モードへ切り替え、入力へフォーカスを渡す。
// 本文の textarea はプレビュー中も隠したまま置いてあり（「元に戻す」の履歴を保つため）、
// 表示されてからでないとフォーカスできないので、要求を ref に控えておき、モードが切り替わった
// 後の effect で実際にフォーカスする。タブで編集へ戻ったときは、隠す前のカーソルと
// スクロール位置のまま続きから書けるようにする。
// Switches to edit mode when the preview (body or title) is clicked and hands focus to the
// input. The body textarea stays mounted but hidden during the preview (to keep its undo
// history) and can only take focus once shown, so the request is parked in a ref and honoured by
// the effect that runs after the mode flips. Returning through the edit tab resumes at the caret
// and scroll position the textarea had before it was hidden.
export function useMemoDetailEditFocus({ previewMode, setPreviewMode, bodySource }: UseMemoDetailEditFocusParams) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const titleInputRef = useRef<HTMLInputElement>(null);
  const pendingTargetRef = useRef<{ target: MemoDetailEditTarget; position?: MemoEditPosition } | null>(null);
  const bodySourceRef = useRef(bodySource);
  bodySourceRef.current = bodySource;
  const wasPreviewRef = useRef(previewMode);
  // 隠すと scrollTop は 0 に戻るので、見えている間の値を控えておく
  // Hiding resets scrollTop to 0, so remember the value while the textarea is visible
  const bodyScrollTopRef = useRef(0);

  const rememberBodyScroll = useCallback(() => {
    const textarea = textareaRef.current;
    if (textarea && !textarea.hidden) bodyScrollTopRef.current = textarea.scrollTop;
  }, []);

  const beginEditing = useCallback((target: MemoDetailEditTarget, position?: MemoEditPosition) => {
    pendingTargetRef.current = { target, position };
    setPreviewMode(false);
  }, [setPreviewMode]);

  useLayoutEffect(() => {
    const cameFromPreview = wasPreviewRef.current;
    wasPreviewRef.current = previewMode;
    if (previewMode) {
      pendingTargetRef.current = null;
      return;
    }
    const request = pendingTargetRef.current;
    pendingTargetRef.current = null;
    if (!request) {
      const textarea = textareaRef.current;
      if (cameFromPreview && textarea) {
        textarea.focus({ preventScroll: true });
        textarea.scrollTop = bodyScrollTopRef.current;
      }
      return;
    }
    const { target, position } = request;

    const element = target === "title" ? titleInputRef.current : textareaRef.current;
    if (!element) return;
    // クリックでは指定位置、Enter では従来どおり末尾から編集する。
    // Clicks retain their source position; Enter keeps the append shortcut.
    const rawOffset = position ? position.offset ?? 0 : element.value.length;
    // textarea は改行を \n にそろえるので、本文に対する位置をその分だけ詰める
    // A textarea normalises line breaks to \n, so shrink the source offset accordingly
    const offset = element instanceof HTMLTextAreaElement && position
      ? Math.min(bodySourceRef.current.slice(0, rawOffset).replace(/\r\n?/g, "\n").length, element.value.length)
      : Math.min(rawOffset, element.value.length);
    element.focus({ preventScroll: true });
    element.setSelectionRange(offset, offset);
    if (element instanceof HTMLTextAreaElement) {
      if (position) alignTextareaToClick(element, { ...position, offset: position.offset === null ? null : offset });
      else element.scrollTop = element.scrollHeight;
      bodyScrollTopRef.current = element.scrollTop;
    }
  }, [previewMode]);

  return { textareaRef, titleInputRef, beginEditing, rememberBodyScroll };
}
