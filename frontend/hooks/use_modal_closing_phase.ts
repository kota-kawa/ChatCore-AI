// 開いていた面が閉じた直後の MODAL_EXIT_DURATION_MS の間だけ true を返す。ModalShell を使えない入れ子の面（拡大表示など）が、閉じる動きを描く間アンマウントを遅らせるために使う。
// Returns true only for MODAL_EXIT_DURATION_MS right after an open surface closes. For nested surfaces that cannot use ModalShell (e.g. an expanded viewer) to delay unmounting while the closing motion plays.
import { useEffect, useState } from "react";

import { MODAL_EXIT_DURATION_MS } from "../components/ui/modal_shell";

// 呼び出し元は `isOpen || isClosing` の間だけ面を描き、isClosing の間は `is-closing` を付けて `inert` にする。
// 閉じる途中に isOpen が true に戻ると、タイマーを捨てて直ちに開き直した扱いになる。
// Callers draw the surface while `isOpen || isClosing`, add `is-closing` and `inert` during isClosing.
// If isOpen turns true again mid-close, the timer is dropped and the surface counts as reopened at once.
export function useModalClosingPhase(isOpen: boolean): boolean {
  // 前回の値と比べて描画中に state を合わせる（ModalShell と同じ方式）
  // Adjust state during render against the previous value (same approach as ModalShell)
  const [previousIsOpen, setPreviousIsOpen] = useState(isOpen);
  const [isClosing, setIsClosing] = useState(false);
  if (previousIsOpen !== isOpen) {
    setPreviousIsOpen(isOpen);
    setIsClosing(!isOpen);
  }

  useEffect(() => {
    if (!isClosing) return;
    const timer = window.setTimeout(() => setIsClosing(false), MODAL_EXIT_DURATION_MS);
    return () => window.clearTimeout(timer);
  }, [isClosing]);

  return isClosing;
}
