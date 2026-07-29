// 表示言語が切り替わるときの画面演出をまとめたモジュール。
// 言語切り替えはページ全体の文言が一斉に入れ替わるため、何も演出しないと
// 「一瞬ちらついた」ようにしか見えない。切り替わったことが伝わる短い
// フェードを添えて、意図した変化であることを示す。
// Screen transition helpers for display-language changes.
// A language switch swaps every label at once, so without any motion it merely
// looks like a glitch. A short fade communicates that the change was intentional.

// ルート要素に付ける演出用の属性。値は "settle"（切り替え直後のフェードイン）と
// "leave"（再読み込み前のフェードアウト）の2種類。
// Transition attribute set on the root element. Values are "settle" (fade-in right
// after a swap) and "leave" (fade-out before a reload).
export const LOCALE_TRANSITION_ATTRIBUTE = "data-cc-locale-transition";

// 再読み込みをまたいで演出を続けるためのフラグ。_document のブートストラップ
// スクリプトが描画前に読み出し、フェードインの初期状態を適用する。
// Flag that carries the transition across a reload. The bootstrap script in
// _document reads it before paint and applies the fade-in starting state.
export const LOCALE_TRANSITION_SESSION_KEY = "chatcore.locale.transition";

// 切り替え直後のフェードイン時間。CSS の cc-locale-settle と一致させること。
// Fade-in duration after a swap. Keep in sync with the cc-locale-settle keyframes.
const SETTLE_MS = 280;
// 再読み込み前のフェードアウト時間。CSS の transition と一致させること。
// Fade-out duration before a reload. Keep in sync with the CSS transition.
const LEAVE_MS = 150;

let settleTimer: number | null = null;

function prefersReducedMotion() {
  return typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function clearSettleTimer() {
  if (settleTimer === null) return;
  window.clearTimeout(settleTimer);
  settleTimer = null;
}

/**
 * 言語の切り替えを適用し、切り替わったことが分かるフェードインを再生する。
 * 状態の更新（apply）は遅延させず即座に実行する。遅延させると、連続で
 * 切り替えたときに前の更新が取りこぼされ「切り替わらない」不具合になるため。
 *
 * Apply a language switch and play a fade-in that makes the change legible.
 * The state update (apply) runs immediately and is never deferred — deferring it
 * drops updates when switching repeatedly, which reads as "the switch did nothing".
 */
export function runLocaleTransition(apply: () => void) {
  apply();

  if (typeof document === "undefined" || prefersReducedMotion()) return;

  const root = document.documentElement;
  clearSettleTimer();
  // 連続で切り替えたときにアニメーションを頭から再生し直す。属性を外して
  // 強制的にレイアウトを再計算しないと、同じ値の再設定では再生されない。
  // Restart the animation on rapid switches: without removing the attribute and
  // forcing a reflow, re-setting the same value does not replay it.
  root.removeAttribute(LOCALE_TRANSITION_ATTRIBUTE);
  void root.offsetWidth;
  root.setAttribute(LOCALE_TRANSITION_ATTRIBUTE, "settle");

  settleTimer = window.setTimeout(() => {
    root.removeAttribute(LOCALE_TRANSITION_ATTRIBUTE);
    settleTimer = null;
  }, SETTLE_MS);
}

/**
 * ページ全体を再読み込みして言語を適用する。再読み込みは白い画面を挟むため、
 * 先にフェードアウトし、次の文書ではフェードインから始めて繋がりを保つ。
 *
 * Reload the whole page to apply the language. A reload flashes a blank frame, so
 * fade out first and let the next document start from a fade-in to bridge the gap.
 */
export function reloadWithLocaleTransition() {
  if (typeof document === "undefined" || prefersReducedMotion()) {
    window.location.reload();
    return;
  }

  try { window.sessionStorage.setItem(LOCALE_TRANSITION_SESSION_KEY, "1"); } catch { /* storage can be unavailable */ }
  clearSettleTimer();
  document.documentElement.setAttribute(LOCALE_TRANSITION_ATTRIBUTE, "leave");
  window.setTimeout(() => window.location.reload(), LEAVE_MS);
}

/**
 * 再読み込み直後のフェードインを終了させ、演出用の属性を取り除く。
 * 属性は _document のブートストラップスクリプトが描画前に付けている。
 *
 * End the post-reload fade-in and drop the transition attribute, which the
 * bootstrap script in _document sets before paint.
 */
export function finishBootLocaleTransition() {
  const root = document.documentElement;
  if (root.getAttribute(LOCALE_TRANSITION_ATTRIBUTE) !== "settle") return;

  clearSettleTimer();
  settleTimer = window.setTimeout(() => {
    root.removeAttribute(LOCALE_TRANSITION_ATTRIBUTE);
    settleTimer = null;
  }, SETTLE_MS);
}
