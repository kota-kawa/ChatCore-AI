// メニューやプルダウンを開いている間、Escape で閉じて開くボタンへフォーカスを戻すフック。外側の押下で閉じる処理は use_dismiss_on_outside_press.ts が担う。
// Hook that, while a menu or dropdown is open, closes it on Escape and returns focus to its trigger. Closing on an outside press belongs to use_dismiss_on_outside_press.ts.
import { useEffect, useRef, type RefObject } from "react";

import { isImeCompositionKeyEvent } from "../lib/ui/ime_composition";

const CAPTURE: AddEventListenerOptions = { capture: true };

// window の capture で最初に Escape を受け、既定動作を打ち消してから閉じる。
// ModalShell のフォーカストラップなど後続の Escape 処理は defaultPrevented を見て退くので、1 回の Escape でメニューだけが閉じる。
// 他の処理がすでに Escape を扱った場合と、IME の変換を取り消す Escape は無視する（判定は入力欄と同じ isImeCompositionKeyEvent）。
// Catch Escape first on the window capture phase and cancel its default before closing. Later Escape handlers such as
// ModalShell's focus trap bail out on defaultPrevented, so one Escape closes only the menu. An Escape that something
// else already handled, or one that cancels an IME composition (detected like text inputs do, via isImeCompositionKeyEvent),
// is ignored.
export function useDismissOnEscape(open: boolean, onDismiss: () => void, triggerRef: RefObject<HTMLElement | null>) {
  // 呼び出し元がインライン関数を渡しても、開いている間に張り直さないよう ref で最新を参照する
  // Read the latest callback through a ref so an inline function from the caller never re-subscribes while open
  const onDismissRef = useRef(onDismiss);
  useEffect(() => {
    onDismissRef.current = onDismiss;
  }, [onDismiss]);

  useEffect(() => {
    if (!open) return undefined;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented || isImeCompositionKeyEvent(event)) return;
      event.preventDefault();
      onDismissRef.current();
      triggerRef.current?.focus();
    };
    window.addEventListener("keydown", handleKeyDown, CAPTURE);
    return () => window.removeEventListener("keydown", handleKeyDown, CAPTURE);
  }, [open, triggerRef]);
}
