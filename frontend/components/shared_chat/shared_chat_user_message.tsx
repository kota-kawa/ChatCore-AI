import { memo, useEffect, useLayoutEffect, useMemo, useRef } from "react";

import { formatUserInputForDisplay } from "../../scripts/chat/chat_ui";
import { renderSanitizedHTML } from "../../scripts/chat/message_utils";

// SSR環境ではuseEffect、クライアント環境ではuseLayoutEffectを使用する（ハイドレーション互換）
// Use useEffect on SSR and useLayoutEffect on client for hydration compatibility
const useIsomorphicLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;

type SharedChatUserMessageProps = {
  text: string;
};

// 共有ページのユーザーメッセージ本文。
// 通常チャットの UserMessageHtml と同じ整形結果を使うが、描画はマウント後の DOM 書き込みで行う。
// サニタイズは DOMPurify（＝DOM）に依存し、サーバー側ではHTMLがエスケープされてしまうため、
// dangerouslySetInnerHTML でSSRするとハイドレーション不一致でタグが文字として残る。
// User message body for the shared page. It reuses the regular chat's formatting, but writes to
// the DOM after mount: sanitization depends on DOMPurify (a DOM API) and falls back to escaping
// on the server, so server-rendering it would leave escaped tags visible after hydration.
function SharedChatUserMessageComponent({ text }: SharedChatUserMessageProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const formatted = useMemo(() => (typeof window === "undefined" ? "" : formatUserInputForDisplay(text)), [text]);

  useIsomorphicLayoutEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    renderSanitizedHTML(container, formatted);
  }, [formatted]);

  return <div ref={containerRef}></div>;
}

// 不要な再レンダリングを防ぐためにメモ化する
// Memoized to prevent unnecessary re-renders
export const SharedChatUserMessage = memo(SharedChatUserMessageComponent);
SharedChatUserMessage.displayName = "SharedChatUserMessage";
