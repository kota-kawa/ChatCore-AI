import { useEffect, useState } from "react";

// 画面上キーボードで縮む「表示領域（visual viewport）」の高さを px で返す。
// レイアウトビューポート（100vh / window.innerHeight）はキーボードが出ても縮まないため、
// キーボードに隠れない大きさを CSS で決めたい要素はこの値を使う。
// Returns the height of the visual viewport - the area the on-screen keyboard shrinks - in px.
// The layout viewport (100vh / window.innerHeight) does not shrink when the keyboard opens, so
// anything that must stay clear of the keyboard sizes itself from this value instead.
//
// 計測前（SSR とマウント直後）は null を返す。呼び出し側は CSS 側のフォールバックへ委ねる。
// Returns null until the first measurement (SSR and the first render) so callers can fall back
// to their CSS default.

// iOS はキーボードを閉じた直後の resize が遅れることがあるため、フォーカスが外れたら測り直す。
// iOS can delay the resize that follows a keyboard dismissal, so re-measure after focus leaves.
const FOCUS_SETTLE_MS = 250;

export function useVisualViewportHeight(enabled: boolean): number | null {
  const [height, setHeight] = useState<number | null>(null);

  useEffect(() => {
    if (!enabled) {
      setHeight(null);
      return undefined;
    }

    let frameId: number | null = null;
    let settleTimer: number | null = null;

    const measure = () => {
      frameId = null;
      const next = Math.round(window.visualViewport?.height ?? window.innerHeight);
      setHeight((current) => (current === next ? current : next));
    };

    // resize / scroll は連続で飛んでくるので、1フレームにまとめる
    // resize and scroll fire in bursts, so coalesce them into a single frame
    const scheduleMeasure = () => {
      if (frameId !== null) return;
      frameId = window.requestAnimationFrame(measure);
    };

    const scheduleSettleMeasure = () => {
      if (settleTimer !== null) window.clearTimeout(settleTimer);
      settleTimer = window.setTimeout(() => {
        settleTimer = null;
        measure();
      }, FOCUS_SETTLE_MS);
    };

    measure();
    window.addEventListener("resize", scheduleMeasure);
    window.addEventListener("orientationchange", scheduleMeasure);
    window.visualViewport?.addEventListener("resize", scheduleMeasure);
    window.visualViewport?.addEventListener("scroll", scheduleMeasure);
    document.addEventListener("focusout", scheduleSettleMeasure);

    return () => {
      if (frameId !== null) window.cancelAnimationFrame(frameId);
      if (settleTimer !== null) window.clearTimeout(settleTimer);
      window.removeEventListener("resize", scheduleMeasure);
      window.removeEventListener("orientationchange", scheduleMeasure);
      window.visualViewport?.removeEventListener("resize", scheduleMeasure);
      window.visualViewport?.removeEventListener("scroll", scheduleMeasure);
      document.removeEventListener("focusout", scheduleSettleMeasure);
    };
  }, [enabled]);

  return height;
}
