import { memo, useEffect, useLayoutEffect, useMemo, useRef } from "react";

import { formatLLMOutput } from "../../scripts/chat/chat_ui";
import { initMessageCopyButtons } from "../../scripts/chat/message_copy_buttons";
import { patchSanitizedHTML } from "../../scripts/chat/message_utils";
import { prefersReducedMotion } from "../../lib/chat_page/dom";
import {
  applyStreamingWordReveal,
  clearStreamingWordReveal
} from "../../lib/chat_page/streaming_word_dom";
import { WordRevealTimeline } from "../../lib/chat_page/streaming_word_reveal";
import {
  bindWebSearchSourcesInteractions,
  syncWebSearchSourcesState
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

  // 出典UIのイベントはマウント時に一度だけ委譲する。生成中の再描画ごとに貼り替えると
  // 開閉アニメーションが打ち切られ、クリックが無視されてしまう。本文の挿入より先に
  // 登録するため、この効果は描画の効果より前に宣言する。
  // Delegate the source UI events once on mount: re-attaching them on every
  // streaming re-render tore down handlers mid-animation and made clicks look
  // ignored. Declared before the render effect so the listeners exist before any
  // content (and therefore any favicon load) is inserted.
  useIsomorphicLayoutEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    return bindWebSearchSourcesInteractions(container);
  }, []);

  // コードブロックとコピー枠のコピーボタンは、この本文の中に描かれる。委譲先の
  // document リスナーはページ側の初期化に任せず、ボタンを出す当人が用意する。
  // The copy buttons of code blocks and copy cards are rendered inside this body, so the
  // delegated document listener is set up by whoever renders them, not by page-level init.
  useIsomorphicLayoutEffect(() => {
    initMessageCopyButtons();
  }, []);

  // DOMへの書き込みはレイアウト計算前に行う必要があるためuseIsomorphicLayoutEffectを使用する
  // Use useIsomorphicLayoutEffect as DOM writes must occur before layout calculations
  useIsomorphicLayoutEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    // 差分適用の前に単語spanを畳み、実DOMをHTMLと同じ形に戻す。
    // Fold away the reveal spans first so the live DOM matches the incoming HTML.
    clearStreamingWordReveal(container);
    patchSanitizedHTML(container, formatted);
    // 生成が終わった描画ではspanを付けないため、完成後のDOMに残骸は残らない
    // The finished render adds no spans, so completed messages keep a clean DOM
    if (streaming && !prefersReducedMotion()) {
      if (!revealTimelineRef.current) revealTimelineRef.current = new WordRevealTimeline();
      applyStreamingWordReveal(container, revealTimelineRef.current);
    } else {
      revealTimelineRef.current = null;
    }
    syncWebSearchSourcesState(container);
  }, [formatted, streaming]);

  return <div ref={containerRef}></div>;
}

// 不要な再レンダリングを防ぐためにメモ化する
// Memoized to prevent unnecessary re-renders
export const BotMessageHtml = memo(BotMessageHtmlComponent);
BotMessageHtml.displayName = "BotMessageHtml";
