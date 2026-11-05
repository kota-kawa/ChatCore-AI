// チャット画面向けの DOM 判定の補助（最下部に近いか、モーションを減らす設定か）。
// DOM check helpers for the chat page: whether near the bottom, and whether reduced motion is requested.
import { STICKY_SCROLL_BOTTOM_THRESHOLD_PX } from "./constants";

// スクロール位置が末尾から thresholdPx 以内か。メッセージが増えたときに自動スクロールするかの判断に使う。
// Whether the scroll position is within thresholdPx of the end; used to decide whether to auto-scroll when messages are added.
export function isNearBottom(container: HTMLElement, thresholdPx = STICKY_SCROLL_BOTTOM_THRESHOLD_PX) {
  const distanceToBottom = container.scrollHeight - (container.scrollTop + container.clientHeight);
  return distanceToBottom <= thresholdPx;
}

// 利用者のprefers-reduced-motion設定が有効かどうかを確認する。
// Check whether the user's prefers-reduced-motion setting is active.
export function prefersReducedMotion() {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
