// AI 回答の本文（Markdown 由来のテキスト）をサニタイズ済み HTML として描画する。生成中は末尾の語をフェードインさせ、
// 描き直しが重いときは頻度を落とす。
// Renders the AI answer body as sanitized HTML. While it is still streaming, the trailing words fade in
// and heavy re-renders are spaced out.
import { memo, useEffect, useLayoutEffect, useRef } from "react";

import { formatLLMOutput } from "../../lib/chat_page/message_format/chat_ui";
import { initMessageCopyButtons } from "../../lib/chat_page/message_format/message_copy_buttons";
import { patchSanitizedHTML } from "../../lib/chat_page/message_format/message_utils";
import { prefersReducedMotion } from "../../lib/chat_page/dom";
import { streamRenderGapMs } from "../../lib/chat_page/streaming_render_pace";
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
  // 間引いている間に届いた最新の内容。予約した描き直しは、予約時ではなく実行時の内容を描く。
  // The latest props received while renders are spaced out: a deferred render draws what is current
  // when it runs, not what was current when it was scheduled.
  const latestRef = useRef({ text, streaming });
  // 次に描き直してよい時刻と、そこまで待っている予約。
  // The earliest time the next render may run, and the timer waiting for it.
  const nextRenderAtRef = useRef(0);
  const deferredRenderTimerRef = useRef<number | null>(null);

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
    latestRef.current = { text, streaming };

    const cancelDeferredRender = () => {
      if (deferredRenderTimerRef.current === null) return;
      window.clearTimeout(deferredRenderTimerRef.current);
      deferredRenderTimerRef.current = null;
    };

    const renderLatest = () => {
      const container = containerRef.current;
      if (!container) return;
      const latest = latestRef.current;
      const startedAt = performance.now();
      // 差分適用の前に単語spanを畳み、実DOMをHTMLと同じ形に戻す。
      // Fold away the reveal spans first so the live DOM matches the incoming HTML.
      clearStreamingWordReveal(container);
      // innerHTML を丸ごと置き換えず差分だけ反映するので、ストリーミング中も既存のノード（選択範囲やコピーボタンなど）が保たれる
      // Apply only the diff instead of replacing innerHTML, so existing nodes (selection, copy buttons, etc.) survive while streaming
      patchSanitizedHTML(container, formatLLMOutput(latest.text));
      // 生成が終わった描画ではspanを付けないため、完成後のDOMに残骸は残らない
      // The finished render adds no spans, so completed messages keep a clean DOM
      if (latest.streaming && !prefersReducedMotion()) {
        if (!revealTimelineRef.current) revealTimelineRef.current = new WordRevealTimeline();
        applyStreamingWordReveal(container, revealTimelineRef.current);
      } else {
        revealTimelineRef.current = null;
      }
      syncWebSearchSourcesState(container);
      const finishedAt = performance.now();
      nextRenderAtRef.current = finishedAt + streamRenderGapMs(finishedAt - startedAt);
    };

    // 生成が終わった本文は待たせずに描く。確定した内容を、予約済みの古い描き直しが後から触ることもない。
    // A finished body is rendered without waiting, and no deferred render is left to touch it afterwards.
    if (!streaming) {
      cancelDeferredRender();
      renderLatest();
      return;
    }
    // 予約済みの描き直しが、実行時に最新の本文を拾う。
    // A render that is already scheduled picks up the latest text when it runs.
    if (deferredRenderTimerRef.current !== null) return;

    const waitMs = nextRenderAtRef.current - performance.now();
    if (waitMs <= 0) {
      renderLatest();
      return;
    }
    deferredRenderTimerRef.current = window.setTimeout(() => {
      deferredRenderTimerRef.current = null;
      renderLatest();
    }, waitMs);
  }, [text, streaming]);

  // 予約した描き直しを、外した後のコンテナへ走らせない。
  // Never let a deferred render run after unmount.
  useEffect(
    () => () => {
      if (deferredRenderTimerRef.current === null) return;
      window.clearTimeout(deferredRenderTimerRef.current);
      deferredRenderTimerRef.current = null;
    },
    [],
  );

  return <div ref={containerRef}></div>;
}

// 不要な再レンダリングを防ぐためにメモ化する
// Memoized to prevent unnecessary re-renders
export const BotMessageHtml = memo(BotMessageHtmlComponent);
BotMessageHtml.displayName = "BotMessageHtml";
