import { useEffect, useRef } from "react";

/**
 * 入力コンテナ（.input-container）の実高さを親 .chat-area の CSS 変数
 * --chat-footer-height に反映する。
 * フッターを透明なオーバーレイとして浮かせるレイアウトでは、テキスト行数や
 * 添付チップの増減で入力欄の高さが変わるため、メッセージ一覧の下端余白と
 * スクロールボタンの位置をこの変数経由で追従させる。
 *
 * Mirrors the composer's rendered height into the --chat-footer-height CSS
 * variable on the parent .chat-area so the message list padding and the
 * scroll-to-bottom button track the floating composer as it grows or shrinks.
 */
export function useChatFooterHeight<T extends HTMLElement>() {
  const footerRef = useRef<T | null>(null);

  useEffect(() => {
    const footer = footerRef.current;
    const chatArea = footer?.parentElement;
    if (!footer || !chatArea) {
      return;
    }

    const apply = () => {
      chatArea.style.setProperty("--chat-footer-height", `${footer.offsetHeight}px`);
    };
    apply();

    if (typeof ResizeObserver !== "function") {
      return () => {
        chatArea.style.removeProperty("--chat-footer-height");
      };
    }

    const observer = new ResizeObserver(apply);
    observer.observe(footer);
    return () => {
      observer.disconnect();
      chatArea.style.removeProperty("--chat-footer-height");
    };
  }, []);

  return footerRef;
}
