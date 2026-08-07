// ボットメッセージ内のWeb検索出典UI（アコーディオン開閉・favicon・オーバーフロー制御）
// のDOM挙動。生成中はメッセージが毎フレーム再描画されるため、リスナは要素ごとに
// 貼らずコンテナへ一度だけ委譲する。要素単位で貼り直すと、再描画のたびに
// 登録解除が挟まって開閉アニメーションが打ち切られ、クリックが無視されていた。
// DOM behaviour for the web-search source UI inside bot messages (accordion
// toggling, favicons, overflow handling). Messages re-render every frame while
// generating, so listeners are delegated to the container once instead of being
// attached per element: re-attaching them per render tore down handlers
// mid-animation and made clicks look ignored.

import { prefersReducedMotion } from "./dom";

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

const ROOT_DETAILS_SELECTOR = "details.web-search-sources";
const ROOT_SUMMARY_SELECTOR = ".web-search-sources__summary";
const NESTED_DETAILS_SELECTOR =
  "details.web-search-sources__step-details, details.web-search-sources__source-details";
const OPEN_NESTED_DETAILS_SELECTOR =
  "details.web-search-sources__step-details[open], details.web-search-sources__source-details[open]";
const FAVICON_SELECTOR = "img.web-search-citation__favicon";
const CITATION_ICON_SELECTOR = ".web-search-citation__icon";
const CITATION_ICON_FALLBACK_CLASS = "web-search-citation__icon--fallback";

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
function updateWebSearchOverflowState(element: HTMLElement) {
  const row = element.closest<HTMLElement>(".chat-message-row");
  const wrapper = element.closest<HTMLElement>(".message-wrapper");
  const hasOpenSourceDetails = Boolean(row?.querySelector(OPEN_NESTED_DETAILS_SELECTOR));

  [row, wrapper].forEach((target) => {
    if (!target) return;
    if (hasOpenSourceDetails) {
      target.dataset.webSearchOverflowActive = "true";
      return;
    }
    delete target.dataset.webSearchOverflowActive;
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

// 展開したWebソースがスクローラー内に収まるようにスクロール位置を調整する
// Adjust the scroll position so expanded web sources are visible within the scroller
function revealWebSearchSources(details: HTMLElement) {
  const scroller = details.closest<HTMLElement>(".chat-messages");
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
function scheduleWebSearchSourcesReveal(details: HTMLElement) {
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
    // 高さアニメーションと競合しないよう、最終サイズになってからスクロールを寄せる。
    // Only nudge the scroll position once the panel has reached its final size,
    // so the reveal no longer fights the height animation mid-flight.
    if (shouldOpen) scheduleWebSearchSourcesReveal(details);
  };
}

// faviconの読み込みが失敗している出典アイコンをフォールバック表示へ切り替える。
// Switch source icons whose favicon failed to load over to the fallback initial.
function showCitationFallback(favicon: HTMLImageElement) {
  favicon
    .closest<HTMLElement>(CITATION_ICON_SELECTOR)
    ?.classList.add(CITATION_ICON_FALLBACK_CLASS);
}

// 描画（差分パッチ）直後に、実行時の状態を実DOMへ合わせ直す。
// 読み込み済みで失敗しているfaviconはerrorイベントが来ないため、ここで拾う。
// Re-align runtime state with the live DOM right after a render (patch).
// A favicon that already finished loading and failed fires no error event, so
// it is picked up here.
export function syncWebSearchSourcesState(container: HTMLElement) {
  container.querySelectorAll<HTMLImageElement>(FAVICON_SELECTOR).forEach((favicon) => {
    if (favicon.complete && favicon.naturalWidth === 0) showCitationFallback(favicon);
  });
  updateWebSearchOverflowState(container);
}

// 出典UIのイベントをコンテナへ委譲し、解除関数を返す。マウント中は貼り替えない。
// Delegate the source UI events to the container and return a cleanup function.
// The listeners stay in place for the whole mounted lifetime.
export function bindWebSearchSourcesInteractions(container: HTMLElement) {
  const handleClick = (event: MouseEvent) => {
    if (!(event.target instanceof Element)) return;
    const summary = event.target.closest<HTMLElement>(ROOT_SUMMARY_SELECTOR);
    if (!summary || !container.contains(summary)) return;
    const details = summary.closest<HTMLDetailsElement>(ROOT_DETAILS_SELECTOR);
    if (!details) return;

    event.preventDefault();
    const shouldOpen = !details.open || details.dataset.webSearchSourcesState === "closing";
    animateWebSearchSources(details, shouldOpen);
  };

  // error と toggle はバブルしないため、キャプチャ段階で受け取る。
  // error and toggle do not bubble, so they are captured on the way down.
  const handleError = (event: Event) => {
    const target = event.target;
    if (!(target instanceof HTMLImageElement) || !target.matches(FAVICON_SELECTOR)) return;
    showCitationFallback(target);
  };

  const handleToggle = (event: Event) => {
    const target = event.target;
    if (!(target instanceof HTMLDetailsElement) || !target.matches(NESTED_DETAILS_SELECTOR)) return;
    updateWebSearchOverflowState(target);
    if (target.open) scheduleWebSearchSourcesReveal(target);
  };

  container.addEventListener("click", handleClick);
  container.addEventListener("error", handleError, true);
  container.addEventListener("toggle", handleToggle, true);

  return () => {
    container.removeEventListener("click", handleClick);
    container.removeEventListener("error", handleError, true);
    container.removeEventListener("toggle", handleToggle, true);
    container.querySelectorAll<HTMLDetailsElement>(ROOT_DETAILS_SELECTOR).forEach((details) => {
      cancelWebSearchSourcesAnimation(details);
      const list = getWebSearchSourcesList(details);
      if (list) resetWebSearchSourcesListStyles(list);
    });
    const row = container.closest<HTMLElement>(".chat-message-row");
    const wrapper = container.closest<HTMLElement>(".message-wrapper");
    if (row) delete row.dataset.webSearchOverflowActive;
    if (wrapper) delete wrapper.dataset.webSearchOverflowActive;
  };
}
