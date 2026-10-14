import { useEffect, useLayoutEffect, useRef } from "react";

const useIsomorphicLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;

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
 *
 * isEnabled が false の間は非表示チャットの observer を停止する。直前の値は退出アニメーション中も保持し、
 * 表示へ戻るときに paint 前のレイアウト effect で更新する。
 *
 * When isEnabled is false, the hidden chat disconnects its observer. The last
 * value stays in place through the exit transition and is refreshed before paint on return.
 */
export function useChatFooterHeight<T extends HTMLElement>(isEnabled: boolean) {
  const footerRef = useRef<T | null>(null);

  useIsomorphicLayoutEffect(() => {
    if (!isEnabled) return;

    const footer = footerRef.current;
    const chatArea = footer?.parentElement;
    if (!footer || !chatArea) {
      return;
    }

    const apply = () => {
      const height = `${footer.offsetHeight}px`;
      if (chatArea.style.getPropertyValue("--chat-footer-height") !== height) {
        chatArea.style.setProperty("--chat-footer-height", height);
      }
    };
    apply();

    if (typeof ResizeObserver !== "function") {
      return;
    }

    const observer = new ResizeObserver(apply);
    observer.observe(footer);
    return () => {
      observer.disconnect();
    };
  }, [isEnabled]);

  return footerRef;
}
