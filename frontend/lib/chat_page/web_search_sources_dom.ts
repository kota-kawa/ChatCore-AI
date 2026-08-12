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

// Webソース展開アニメーションの設定。
// 所要時間は「開く高さ」に比例させる。固定時間だと、背の高いパネルほど1フレームの
// 移動量が大きくなり、最初の数フレームで一気に開いてから残りが這うように見える。
// イージングも、終端側へ極端に寄ったカーブ（easeOutQuint 相当）は初速が速すぎて
// 同じ症状を強めるため、立ち上がりのある標準カーブにする。
// Expand animation settings for the web source panel.
// The duration scales with the distance travelled: a fixed duration makes taller
// panels move further per frame, so they snap open over the first few frames and
// then crawl. The easing is a standard curve for the same reason — a strongly
// back-loaded curve (easeOutQuint-like) starts far too fast and amplifies that.
const WEB_SEARCH_SOURCES_MIN_DURATION_MS = 200;
const WEB_SEARCH_SOURCES_MAX_DURATION_MS = 440;
const WEB_SEARCH_SOURCES_DURATION_PER_PX = 0.32;
// 閉じる動きは開く動きよりわずかに速いほうが、操作に対する反応として自然に見える。
// Closing slightly faster than opening reads as a more responsive reaction.
const WEB_SEARCH_SOURCES_CLOSE_DURATION_RATIO = 0.82;
const WEB_SEARCH_SOURCES_ANIMATION_EASING = "cubic-bezier(0.4, 0, 0.2, 1)";
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
}

// 移動距離から所要時間を決める。1フレームあたりの移動量をおおよそ一定に保つのが狙い。
// Derive the duration from the distance travelled so the per-frame movement stays
// roughly constant regardless of how tall the panel is.
function resolveWebSearchSourcesDuration(distancePx: number, shouldOpen: boolean) {
  const scaled = WEB_SEARCH_SOURCES_MIN_DURATION_MS + Math.abs(distancePx) * WEB_SEARCH_SOURCES_DURATION_PER_PX;
  const clamped = Math.min(scaled, WEB_SEARCH_SOURCES_MAX_DURATION_MS);
  return shouldOpen ? clamped : clamped * WEB_SEARCH_SOURCES_CLOSE_DURATION_RATIO;
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

// 高さアニメーションが残した「固定された高さ」を解除して、リストを内容なりの高さへ戻す。
// fill: "both" のアニメーションは終了後も終了値を適用し続け、しかもアニメーション由来の
// 値はインラインスタイルより強い。開いた瞬間の高さで固定されたままだと、あとから中の
// 「参照したWebサイト」を開いても枠が伸びず、あふれた内容が下のメッセージへ重なる。
// Release the height an earlier animation pinned onto the list so it can size to its
// content again. A fill: "both" animation keeps applying its end value after it
// finishes, and animated values beat inline styles, so the panel would stay frozen at
// the height it had when it opened — later expanding a step's sources then overflowed
// the panel and painted over the messages below it.
function releaseWebSearchSourcesHeightLock(element: Element) {
  if (typeof element.getAnimations !== "function") return;
  element.getAnimations().forEach((animation) => {
    animation.cancel();
  });
}

// 展開後にスクロールをどれだけ動かすべきかを返す。動かす必要がなければ null。
// Return the scrollTop the scroller should move to after expanding, or null when it
// is already in view.
function resolveWebSearchRevealScrollTop(details: HTMLElement, scroller: HTMLElement) {
  const scrollerRect = scroller.getBoundingClientRect();
  const detailsRect = details.getBoundingClientRect();
  const availableHeight = scrollerRect.height - WEB_SEARCH_SOURCES_REVEAL_PADDING * 2;
  const topGap = detailsRect.top - (scrollerRect.top + WEB_SEARCH_SOURCES_REVEAL_PADDING);
  const bottomGap = detailsRect.bottom - (scrollerRect.bottom - WEB_SEARCH_SOURCES_REVEAL_PADDING);

  // パネルが画面に収まるなら、はみ出した側だけを寄せる。
  // While the panel fits, only nudge whichever edge is out of view.
  if (detailsRect.height <= availableHeight) {
    if (topGap < 0) return scroller.scrollTop + topGap;
    if (bottomGap > 0) return scroller.scrollTop + bottomGap;
    return null;
  }

  // 収まらない場合は先頭を見せる。
  // When it cannot fit, show its top edge instead.
  if (topGap < 0 || bottomGap > 0) return scroller.scrollTop + topGap;
  return null;
}

// 展開したWebソースがスクローラー内に収まるようにスクロール位置を調整する。
// 位置合わせは高さアニメーションの直後に起きるため、瞬間移動させると開き終わりに
// 「カクッ」と跳ねて見える。スムーズスクロールで開く動きから繋げる。
// Adjust the scroll position so expanded web sources are visible within the scroller.
// This runs right after the height animation, so jumping scrollTop reads as a hitch
// at the end of the expansion; scroll smoothly to carry the motion through instead.
function revealWebSearchSources(details: HTMLElement) {
  const scroller = details.closest<HTMLElement>(".chat-messages");
  if (!scroller) {
    details.scrollIntoView({ block: "nearest" });
    return;
  }

  const target = resolveWebSearchRevealScrollTop(details, scroller);
  if (target === null) return;

  const maxScrollTop = Math.max(0, scroller.scrollHeight - scroller.clientHeight);
  const clamped = Math.min(Math.max(target, 0), maxScrollTop);
  if (Math.abs(clamped - scroller.scrollTop) < 1) return;

  if (prefersReducedMotion() || typeof scroller.scrollTo !== "function") {
    scroller.scrollTop = clamped;
    return;
  }
  scroller.scrollTo({ top: clamped, behavior: "smooth" });
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

  // 高さと一緒に中身も動かすと、伸びる動きと滑る動きが二重になって落ち着かない。
  // 動かすのは高さだけにして、フェードは高さより先に終わらせる（閉じるときは先に
  // 消える）。動きが一種類なら、フレームが落ちても「かくつき」として目立ちにくい。
  // Moving the content as well as the height stacks two motions on top of each other
  // and reads as unsettled. Animate the height only, and let the fade finish ahead of
  // it (or start ahead of it when closing). A single motion hides dropped frames far
  // better than two competing ones.
  const startOpacity = shouldOpen && startHeight < 1 ? 0 : 1;
  const endOpacity = shouldOpen ? 1 : 0;
  const animation = list.animate(
    [
      { height: `${startHeight}px`, opacity: startOpacity, offset: 0 },
      { opacity: endOpacity, offset: shouldOpen ? 0.5 : 0.7 },
      { height: `${endHeight}px`, opacity: endOpacity, offset: 1 }
    ],
    {
      duration: resolveWebSearchSourcesDuration(endHeight - startHeight, shouldOpen),
      easing: WEB_SEARCH_SOURCES_ANIMATION_EASING,
      fill: "both"
    }
  );

  activeWebSearchSourceAnimations.set(details, animation);
  animation.onfinish = () => {
    if (activeWebSearchSourceAnimations.get(details) !== animation) return;
    activeWebSearchSourceAnimations.delete(details);
    // 終了値を適用したままにせず必ず解除する。残すとリストの高さが固定され、
    // 中のステップを開いたときに伸びずにあふれる。
    // Always release the end value; leaving it pinned freezes the list height and
    // makes a step expanded later overflow instead of growing the panel.
    animation.onfinish = null;
    animation.cancel();
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
    // ステップを開くと外側パネルの中身が伸びる。前回の開閉アニメーションが高さを
    // 固定したままだと伸びられずあふれるため、開閉のたびに固定を解除する。
    // Expanding a step grows the outer panel's content. Release any height an earlier
    // open/close animation pinned, or the panel cannot grow and its content overflows.
    const rootDetails = target.closest<HTMLDetailsElement>(ROOT_DETAILS_SELECTOR);
    // 開閉アニメーションの実行中はそのアニメーションが高さを持っているので触らない。
    // While an open/close animation is running it owns the height, so leave it alone.
    if (rootDetails && !activeWebSearchSourceAnimations.has(rootDetails)) {
      const rootList = getWebSearchSourcesList(rootDetails);
      if (rootList) {
        releaseWebSearchSourcesHeightLock(rootList);
        resetWebSearchSourcesListStyles(rootList);
      }
    }
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
