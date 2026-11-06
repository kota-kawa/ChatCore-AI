// メニューやプルダウンを開いている間、その外側を押したら閉じるだけにするフック。押した先の要素には何も起こさない。
// Hook that, while a menu or dropdown is open, turns a press outside it into a dismissal only: the pressed element gets nothing.
import { useEffect, useRef } from "react";

const CAPTURE: AddEventListenerOptions = { capture: true };
// touchend を打ち消すには passive でない登録が要る / Cancelling touchend needs a non-passive listener
const CAPTURE_ACTIVE: AddEventListenerOptions = { capture: true, passive: false };

let swallowedPress: { pointerDown: PointerEvent; release: () => void } | null = null;

// 閉じるために使った押下を、離すまで（タッチは touchend まで）打ち消す。
// mousedown を止めるとマウスでのフォーカス移動・カーソル配置・範囲選択が起きず、
// touchend を止めるとタッチでのフォーカス移動と click が起きない。click・auxclick・contextmenu も止めて、
// ボタンやリンク（中ボタンで新しいタブを開く操作を含む）や右クリックのメニューを反応させない。
// 押下が終わったら外す。離す操作を受け取れなかったときも次の押下かキー入力で外し、キーボードや
// スクリプトによる click（detail が 0）は打ち消さない。
// Swallow the rest of the press that dismissed the menu. Cancelling mousedown keeps a mouse press from moving
// focus, placing the caret, or starting a selection; cancelling touchend keeps a tap from focusing and from
// producing a click. click, auxclick and contextmenu are stopped too, so buttons, links (including a middle-click
// into a new tab) and the context menu do not react. The listeners come off when the press ends, or at the next
// press or key if its end was never seen, and a keyboard or scripted click (detail 0) is never swallowed.
function swallowRestOfPress(pointerDown: PointerEvent) {
  pointerDown.stopPropagation();
  if (swallowedPress) {
    // 入れ子のメニューが同じ押下で閉じるときは 1 組だけ張る / Nested menus closing on the same press share one set
    if (swallowedPress.pointerDown === pointerDown) return;
    swallowedPress.release();
  }

  const cancel = (event: Event) => {
    if (event.cancelable) event.preventDefault();
    event.stopPropagation();
  };
  const cancelClick = (event: Event) => {
    if ((event as MouseEvent).detail === 0) return;
    cancel(event);
    release();
  };
  // マウスの click は pointerup と同じタスクで届くので、次のタスクで外せば取りこぼさない。
  // タッチは pointerup と touchend が別のタスクで届くブラウザもあるので、touchend を打ち消してから外す。
  // A mouse click arrives in the same task as pointerup, so releasing on the next task still catches it.
  // Some browsers deliver touchend in a later task than pointerup, so a touch press is released after touchend.
  const releaseAfterPointerUp = (event: Event) => {
    event.stopPropagation();
    if ((event as PointerEvent).pointerType === "touch") return;
    window.setTimeout(release, 0);
  };
  const cancelTouchEnd = (event: Event) => {
    cancel(event);
    window.setTimeout(release, 0);
  };
  const listeners: Array<[string, EventListener, AddEventListenerOptions]> = [
    ["mousedown", cancel, CAPTURE],
    ["mouseup", cancel, CAPTURE],
    ["auxclick", cancel, CAPTURE],
    ["contextmenu", cancel, CAPTURE],
    ["touchend", cancelTouchEnd, CAPTURE_ACTIVE],
    ["pointerup", releaseAfterPointerUp, CAPTURE],
    ["pointercancel", () => release(), CAPTURE],
    ["click", cancelClick, CAPTURE],
    ["pointerdown", () => release(), CAPTURE],
    ["keydown", () => release(), CAPTURE],
  ];
  function release() {
    if (swallowedPress?.release !== release) return;
    swallowedPress = null;
    listeners.forEach(([type, listener, options]) => window.removeEventListener(type, listener, options));
  }
  listeners.forEach(([type, listener, options]) => window.addEventListener(type, listener, options));
  swallowedPress = { pointerDown, release };
}

// isInside が true を返す要素（開くボタンとメニュー本体など）の押下は通常どおり扱う。
// 外側の押下は window の capture で最初に受け、onDismiss を呼んでから押下の残りを打ち消す。
// Presses on elements for which isInside returns true (typically the trigger and the menu) behave normally.
// An outside press is caught first, on the window capture phase; onDismiss runs and the rest of the press is swallowed.
export function useDismissOnOutsidePress(open: boolean, isInside: (target: Node) => boolean, onDismiss: () => void) {
  // 呼び出し元がインライン関数を渡しても、開いている間に張り直さないよう ref で最新を参照する
  // Read the latest callbacks through refs so inline functions from the caller never re-subscribe while open
  const isInsideRef = useRef(isInside);
  const onDismissRef = useRef(onDismiss);
  useEffect(() => {
    isInsideRef.current = isInside;
    onDismissRef.current = onDismiss;
  }, [isInside, onDismiss]);

  useEffect(() => {
    if (!open) return undefined;
    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Node) || isInsideRef.current(target)) return;
      onDismissRef.current();
      swallowRestOfPress(event);
    };
    window.addEventListener("pointerdown", handlePointerDown, CAPTURE);
    return () => window.removeEventListener("pointerdown", handlePointerDown, CAPTURE);
  }, [open]);
}
