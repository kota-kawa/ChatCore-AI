import { memo, useEffect, useLayoutEffect, useMemo, useRef } from "react";

import { formatLLMOutput } from "../../scripts/chat/chat_ui";
import { renderSanitizedHTML } from "../../scripts/chat/message_utils";

// SSR環境ではuseEffect、クライアント環境ではuseLayoutEffectを使用する（ハイドレーション互換）
// Use useEffect on SSR and useLayoutEffect on client for hydration compatibility
const useIsomorphicLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;
// Webソース展開アニメーションの設定
// Web source expand animation settings
const WEB_SEARCH_SOURCES_ANIMATION_MS = 170;
const WEB_SEARCH_SOURCES_ANIMATION_EASING = "cubic-bezier(0.22, 1, 0.36, 1)";
// 実行中のWebソースアニメーションを追跡するWeakMap（GCに優しい）
// WeakMap to track active web source animations (GC-friendly)
const activeWebSearchSourceAnimations = new WeakMap<HTMLDetailsElement, Animation>();
// 展開時にスクロールで確保するパディング量（px）
// Padding (px) to ensure while scrolling on expand
const WEB_SEARCH_SOURCES_REVEAL_PADDING = 16;

// ボットメッセージHTMLコンポーネントのprops型定義
// Props type definition for the bot message HTML component
type BotMessageHtmlProps = {
  text: string;
};

// ユーザーのprefers-reduced-motionメディアクエリが有効かどうかを確認する
// Check if the user's prefers-reduced-motion media query is active
function prefersReducedMotion() {
  return typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

// detailsの子要素からWebソース一覧リスト要素を取得する
// Get the web source list element from the children of a details element
function getWebSearchSourcesList(details: HTMLDetailsElement) {
  return Array.from(details.children).find(
    (child): child is HTMLElement =>
      child instanceof HTMLElement && child.classList.contains("web-search-sources__list")
  );
}

// リスト要素のインラインスタイルをリセットする
// Reset inline styles on the list element
function resetWebSearchSourcesListStyles(list: HTMLElement) {
  list.style.height = "";
  list.style.overflow = "";
  list.style.opacity = "";
  list.style.transform = "";
}

// 展開されたWebソースの詳細がビューポートに収まるようにオーバーフロー状態を更新する
// Update overflow state so expanded web source details fit within the viewport
function setWebSearchOverflowState(sourceDetails: HTMLElement) {
  const row = sourceDetails.closest<HTMLElement>(".chat-message-row");
  const wrapper = sourceDetails.closest<HTMLElement>(".message-wrapper");
  const selector = "details.web-search-sources__step-details[open], details.web-search-sources__source-details[open]";
  const hasOpenSourceDetails = Boolean(row?.querySelector(selector));

  [row, wrapper].forEach((element) => {
    if (!element) return;
    if (hasOpenSourceDetails) {
      element.dataset.webSearchOverflowActive = "true";
      return;
    }
    delete element.dataset.webSearchOverflowActive;
  });
}

// 実行中のWebソースアニメーションをキャンセルしてWeakMapから削除する
// Cancel the active web source animation and remove it from the WeakMap
function cancelWebSearchSourcesAnimation(details: HTMLDetailsElement) {
  const activeAnimation = activeWebSearchSourceAnimations.get(details);
  if (!activeAnimation) return;
  activeAnimation.onfinish = null;
  activeAnimation.oncancel = null;
  activeAnimation.cancel();
  activeWebSearchSourceAnimations.delete(details);
}

// チャットメッセージスクローラーのDOM要素を取得する
// Get the DOM element of the chat messages scroller
function getChatMessagesScroller(element: HTMLElement) {
  return element.closest<HTMLElement>(".chat-messages");
}

// 展開したWebソースがスクローラー内に収まるようにスクロール位置を調整する
// Adjust the scroll position so expanded web sources are visible within the scroller
function revealWebSearchSources(details: HTMLDetailsElement) {
  const scroller = getChatMessagesScroller(details);
  if (!scroller) {
    details.scrollIntoView({ block: "nearest" });
    return;
  }

  const scrollerRect = scroller.getBoundingClientRect();
  const detailsRect = details.getBoundingClientRect();
  const availableHeight = scrollerRect.height - WEB_SEARCH_SOURCES_REVEAL_PADDING * 2;

  if (detailsRect.height <= availableHeight) {
    if (detailsRect.top < scrollerRect.top + WEB_SEARCH_SOURCES_REVEAL_PADDING) {
      scroller.scrollTop -= scrollerRect.top + WEB_SEARCH_SOURCES_REVEAL_PADDING - detailsRect.top;
      return;
    }

    if (detailsRect.bottom > scrollerRect.bottom - WEB_SEARCH_SOURCES_REVEAL_PADDING) {
      scroller.scrollTop += detailsRect.bottom - (scrollerRect.bottom - WEB_SEARCH_SOURCES_REVEAL_PADDING);
    }
    return;
  }

  if (
    detailsRect.top < scrollerRect.top + WEB_SEARCH_SOURCES_REVEAL_PADDING ||
    detailsRect.bottom > scrollerRect.bottom - WEB_SEARCH_SOURCES_REVEAL_PADDING
  ) {
    scroller.scrollTop += detailsRect.top - (scrollerRect.top + WEB_SEARCH_SOURCES_REVEAL_PADDING);
  }
}

// 次のアニメーションフレームでWebソースの表示位置を調整するリクエストをスケジュールする
// Schedule a reveal position adjustment for web sources in the next animation frame
function scheduleWebSearchSourcesReveal(details: HTMLDetailsElement) {
  if (typeof window === "undefined") return;

  window.requestAnimationFrame(() => {
    revealWebSearchSources(details);
  });
}

// WebソースリストのアコーディオンをWeb Animations APIでアニメーション付き開閉する
// Open/close the web source list accordion with animation using the Web Animations API
function animateWebSearchSources(details: HTMLDetailsElement, shouldOpen: boolean) {
  const list = getWebSearchSourcesList(details);
  if (!list || typeof list.animate !== "function" || prefersReducedMotion()) {
    // アニメーション非対応またはモーション軽減設定の場合は即時切り替え
    // Immediately toggle if animation is unsupported or reduced motion is preferred
    cancelWebSearchSourcesAnimation(details);
    details.open = shouldOpen;
    delete details.dataset.webSearchSourcesState;
    if (list) resetWebSearchSourcesListStyles(list);
    if (shouldOpen) scheduleWebSearchSourcesReveal(details);
    return;
  }

  const startHeight = details.open ? list.getBoundingClientRect().height : 0;
  cancelWebSearchSourcesAnimation(details);

  list.style.height = `${startHeight}px`;
  list.style.overflow = "hidden";
  list.style.opacity = shouldOpen || startHeight > 0 ? "1" : "0";
  list.style.transform = "translateY(0)";

  if (shouldOpen) {
    details.open = true;
  }

  const endHeight = shouldOpen ? list.scrollHeight : 0;
  details.dataset.webSearchSourcesState = shouldOpen ? "opening" : "closing";

  // 高さの変化が1px未満の場合はアニメーションをスキップする
  // Skip animation if height change is less than 1px
  if (Math.abs(endHeight - startHeight) < 1) {
    details.open = shouldOpen;
    delete details.dataset.webSearchSourcesState;
    resetWebSearchSourcesListStyles(list);
    if (shouldOpen) scheduleWebSearchSourcesReveal(details);
    return;
  }

  const animation = list.animate(
    [
      {
        height: `${startHeight}px`,
        opacity: shouldOpen && startHeight < 1 ? 0 : 1,
        transform: shouldOpen && startHeight < 1 ? "translateY(-4px)" : "translateY(0)"
      },
      {
        height: `${endHeight}px`,
        opacity: shouldOpen ? 1 : 0,
        transform: shouldOpen ? "translateY(0)" : "translateY(-3px)"
      }
    ],
    {
      duration: WEB_SEARCH_SOURCES_ANIMATION_MS,
      easing: WEB_SEARCH_SOURCES_ANIMATION_EASING,
      fill: "both"
    }
  );

  activeWebSearchSourceAnimations.set(details, animation);
  animation.onfinish = () => {
    if (activeWebSearchSourceAnimations.get(details) !== animation) return;
    activeWebSearchSourceAnimations.delete(details);
    details.open = shouldOpen;
    delete details.dataset.webSearchSourcesState;
    resetWebSearchSourcesListStyles(list);
    // Only nudge the scroll position once the panel has reached its final size,
    // so the reveal no longer fights the height animation mid-flight.
    if (shouldOpen) scheduleWebSearchSourcesReveal(details);
  };
}

// コンテナ内のWebソースアコーディオンにクリックイベントをバインドし、クリーンアップ関数を返す
// Bind click events to web source accordions in the container and return a cleanup function
function bindWebSearchSourcesAccordions(container: HTMLElement) {
  const cleanupCallbacks: Array<() => void> = [];

  container.querySelectorAll<HTMLDetailsElement>("details.web-search-sources").forEach((details) => {
    const summary = details.querySelector<HTMLElement>(".web-search-sources__summary");
    if (!summary) return;

    const handleSummaryClick = (event: MouseEvent) => {
      event.preventDefault();
      const shouldOpen = !details.open || details.dataset.webSearchSourcesState === "closing";
      animateWebSearchSources(details, shouldOpen);
    };

    summary.addEventListener("click", handleSummaryClick);
    cleanupCallbacks.push(() => {
      summary.removeEventListener("click", handleSummaryClick);
      cancelWebSearchSourcesAnimation(details);
      const list = getWebSearchSourcesList(details);
      if (list) resetWebSearchSourcesListStyles(list);
    });
  });

  // ステップ詳細・ソース詳細のトグルイベントでオーバーフロー状態を更新する
  // Update overflow state on toggle events for step details and source details
  container
    .querySelectorAll<HTMLDetailsElement>(
      "details.web-search-sources__step-details, details.web-search-sources__source-details"
    )
    .forEach((details) => {
      const handleToggle = () => {
        setWebSearchOverflowState(details);
        if (details.open) scheduleWebSearchSourcesReveal(details);
      };

      details.addEventListener("toggle", handleToggle);
      setWebSearchOverflowState(details);
      cleanupCallbacks.push(() => {
        details.removeEventListener("toggle", handleToggle);
        const row = details.closest<HTMLElement>(".chat-message-row");
        const wrapper = details.closest<HTMLElement>(".message-wrapper");
        if (row) delete row.dataset.webSearchOverflowActive;
        if (wrapper) delete wrapper.dataset.webSearchOverflowActive;
      });
    });

  return () => {
    cleanupCallbacks.forEach((cleanup) => {
      cleanup();
    });
  };
}

// LLMのボットメッセージをサニタイズされたHTMLとしてレンダリングするコンポーネント
// Component that renders LLM bot messages as sanitized HTML
function BotMessageHtmlComponent({ text }: BotMessageHtmlProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  // テキストが変わった場合のみフォーマット済みHTMLを再計算する
  // Recompute formatted HTML only when text changes
  const formatted = useMemo(() => formatLLMOutput(text), [text]);

  // DOMへの書き込みはレイアウト計算前に行う必要があるためuseIsomorphicLayoutEffectを使用する
  // Use useIsomorphicLayoutEffect as DOM writes must occur before layout calculations
  useIsomorphicLayoutEffect(() => {
    if (!containerRef.current) return;
    renderSanitizedHTML(containerRef.current, formatted);
    return bindWebSearchSourcesAccordions(containerRef.current);
  }, [formatted]);

  return <div ref={containerRef}></div>;
}

// 不要な再レンダリングを防ぐためにメモ化する
// Memoized to prevent unnecessary re-renders
export const BotMessageHtml = memo(BotMessageHtmlComponent);
BotMessageHtml.displayName = "BotMessageHtml";
