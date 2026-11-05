// 領域を隠す前にフォーカスをその外へ逃がす補助（隠した領域にフォーカスが残るのを防ぐ）。
// Helper that moves focus out of a region before hiding it, so focus is never left inside a hidden region.
// 非表示にする領域内にフォーカスがある場合、aria-hidden の反映前に領域外へ退避する。
// Moves focus outside a region before it is hidden from assistive technologies.
export function moveFocusOutOfHiddenRegion(region: HTMLElement | null, fallback?: HTMLElement | null) {
  if (!region || typeof document === "undefined") {
    return false;
  }

  const activeElement = document.activeElement;
  if (!(activeElement instanceof HTMLElement) || !region.contains(activeElement)) {
    return false;
  }

  if (fallback?.isConnected && !region.contains(fallback)) {
    fallback.focus();
  } else {
    activeElement.blur();
  }
  return true;
}
