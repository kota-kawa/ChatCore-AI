import { STICKY_SCROLL_BOTTOM_THRESHOLD_PX } from "./constants";

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
