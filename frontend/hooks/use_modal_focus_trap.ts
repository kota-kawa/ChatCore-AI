import { useEffect, type RefObject } from "react";

const FOCUSABLE_SELECTOR = [
  "button:not([disabled])",
  "[href]",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

/**
 * 指定されたコンテナ内のフォーカス可能な要素を取得する
 * Get focusable elements within the specified container
 */
function getFocusableElements(container: HTMLElement) {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter((element) => {
    // 隠れている要素を除外する
    // Exclude hidden elements
    return !element.hasAttribute("hidden") && element.getAttribute("aria-hidden") !== "true";
  });
}

type UseModalFocusTrapOptions = {
  isOpen: boolean;
  containerRef: RefObject<HTMLElement | null>;
  getInitialFocus?: () => HTMLElement | null;
  onEscape?: () => void;
};

/**
 * モーダル内のフォーカストラップを管理するカスタムフック
 * Custom hook to manage focus trap within a modal
 */
export function useModalFocusTrap({
  isOpen,
  containerRef,
  getInitialFocus,
  onEscape,
}: UseModalFocusTrapOptions) {
  useEffect(() => {
    // モーダルが開いていない場合は何もしない
    // Do nothing if the modal is not open
    if (!isOpen) return;

    // 前にフォーカスされていた要素を保存する
    // Save the previously focused element
    const previousFocusedElement =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;

    // 初期のフォーカスを設定する
    // Set the initial focus
    window.requestAnimationFrame(() => {
      const container = containerRef.current;
      if (!container) return;
      
      // 初期フォーカス要素を決定する
      // Determine the initial focus element
      const initialFocus = getInitialFocus?.() ?? getFocusableElements(container)[0] ?? container;
      initialFocus.focus();
    });

    // キーボードイベントのハンドラ
    // Keyboard event handler
    const onKeyDown = (event: KeyboardEvent) => {
      const container = containerRef.current;
      if (!container) return;

      // Escapeキーが押された場合の処理
      // Handle the Escape key press
      if (event.key === "Escape" && onEscape) {
        event.preventDefault();
        onEscape();
        return;
      }

      // Tabキー以外のキー入力は無視する
      // Ignore key presses other than Tab
      if (event.key !== "Tab") return;

      const focusable = getFocusableElements(container);
      
      // フォーカス可能な要素がない場合、コンテナにフォーカスを戻す
      // If there are no focusable elements, return focus to the container
      if (focusable.length === 0) {
        event.preventDefault();
        container.focus();
        return;
      }

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const activeElement = document.activeElement instanceof HTMLElement ? document.activeElement : null;

      // Shift+Tabキーが押された時の処理：最初の要素から最後の要素へループ
      // Handle Shift+Tab press: loop from the first element to the last
      if (event.shiftKey && (!activeElement || activeElement === first || !container.contains(activeElement))) {
        event.preventDefault();
        last.focus();
        return;
      }

      // Tabキーが押された時の処理：最後の要素から最初の要素へループ
      // Handle Tab press: loop from the last element to the first
      if (!event.shiftKey && (!activeElement || activeElement === last || !container.contains(activeElement))) {
        event.preventDefault();
        first.focus();
      }
    };

    // イベントリスナーを登録する
    // Register the event listener
    document.addEventListener("keydown", onKeyDown);
    
    // クリーンアップ関数
    // Cleanup function
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      
      // モーダルが閉じた後、元の要素にフォーカスを戻す
      // Restore focus to the original element after the modal closes
      if (previousFocusedElement?.isConnected) {
        previousFocusedElement.focus();
      }
    };
  }, [containerRef, getInitialFocus, isOpen, onEscape]);
}
