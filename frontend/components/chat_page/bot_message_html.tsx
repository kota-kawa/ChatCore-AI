import { memo, useEffect, useLayoutEffect, useMemo, useRef } from "react";

import { formatLLMOutput } from "../../scripts/chat/chat_ui";
import { renderSanitizedHTML } from "../../scripts/chat/message_utils";
import { prefersReducedMotion } from "../../lib/chat_page/dom";
import { applyStreamingWordReveal } from "../../lib/chat_page/streaming_word_dom";
import { WordRevealTimeline } from "../../lib/chat_page/streaming_word_reveal";
import {
  bindWebSearchCitationFavicons,
  bindWebSearchSourcesAccordions
} from "../../lib/chat_page/web_search_sources_dom";

// SSR環境ではuseEffect、クライアント環境ではuseLayoutEffectを使用する（ハイドレーション互換）
// Use useEffect on SSR and useLayoutEffect on client for hydration compatibility
const useIsomorphicLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;

// ボットメッセージHTMLコンポーネントのprops型定義
// Props type definition for the bot message HTML component
type BotMessageHtmlProps = {
  text: string;
  // 生成中のテキストパートのみtrue。末尾の語をフェードインさせるかを決める。
  // True only for the text part being generated; gates the word fade-in.
  streaming?: boolean;
};

// LLMのボットメッセージをサニタイズされたHTMLとしてレンダリングするコンポーネント
// Component that renders LLM bot messages as sanitized HTML
function BotMessageHtmlComponent({ text, streaming = false }: BotMessageHtmlProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  // 語ごとの初出時刻。再描画でアニメーションが巻き戻らないように保持する
  // Per-word first-seen times, kept so re-renders do not restart the animation
  const revealTimelineRef = useRef<WordRevealTimeline | null>(null);
  // テキストが変わった場合のみフォーマット済みHTMLを再計算する
  // Recompute formatted HTML only when text changes
  const formatted = useMemo(() => formatLLMOutput(text), [text]);

  // DOMへの書き込みはレイアウト計算前に行う必要があるためuseIsomorphicLayoutEffectを使用する
  // Use useIsomorphicLayoutEffect as DOM writes must occur before layout calculations
  useIsomorphicLayoutEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    renderSanitizedHTML(container, formatted);
    // 生成が終わった描画ではspanを付けないため、完成後のDOMに残骸は残らない
    // The finished render adds no spans, so completed messages keep a clean DOM
    if (streaming && !prefersReducedMotion()) {
      if (!revealTimelineRef.current) revealTimelineRef.current = new WordRevealTimeline();
      applyStreamingWordReveal(container, revealTimelineRef.current);
    } else {
      revealTimelineRef.current = null;
    }
    const cleanupAccordions = bindWebSearchSourcesAccordions(container);
    const cleanupFavicons = bindWebSearchCitationFavicons(container);
    return () => {
      cleanupAccordions();
      cleanupFavicons();
    };
  }, [formatted, streaming]);

  return <div ref={containerRef}></div>;
}

// 不要な再レンダリングを防ぐためにメモ化する
// Memoized to prevent unnecessary re-renders
export const BotMessageHtml = memo(BotMessageHtmlComponent);
BotMessageHtml.displayName = "BotMessageHtml";
