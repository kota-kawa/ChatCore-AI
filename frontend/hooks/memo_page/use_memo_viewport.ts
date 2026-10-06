import { useEffect, useState, type CSSProperties } from "react";

const FOCUS_SETTLE_MS = 250;
const MEMO_MOBILE_QUERY = "(max-width: 768px)";

type ViewportSnapshot = {
  layoutHeight: number;
  height: number;
  top: number;
  bottom: number;
};

type MemoViewportStyle = CSSProperties & {
  "--memo-viewport-height": string;
  "--memo-viewport-top": string;
  "--memo-viewport-bottom": string;
};

function finiteOr(value: number, fallback: number): number {
  return Number.isFinite(value) ? value : fallback;
}

function readViewport(): ViewportSnapshot {
  const layoutHeight = Math.max(0, finiteOr(window.innerHeight, 0));
  const visualViewport = window.visualViewport;
  const scale = visualViewport?.scale;
  const useLayoutViewport = !visualViewport || typeof scale !== "number" || !Number.isFinite(scale) || scale > 1.01;
  const height = useLayoutViewport
    ? layoutHeight
    : Math.max(0, finiteOr(visualViewport.height, layoutHeight));
  const top = useLayoutViewport
    ? 0
    : Math.max(0, finiteOr(visualViewport.offsetTop, 0));
  const bottom = Math.max(0, layoutHeight - height - top);

  return { layoutHeight, height, top, bottom };
}

function toViewportStyle(snapshot: ViewportSnapshot): MemoViewportStyle {
  return {
    "--memo-viewport-height": `${snapshot.height}px`,
    "--memo-viewport-top": `${snapshot.top}px`,
    "--memo-viewport-bottom": `${snapshot.bottom}px`,
  };
}

function sameSnapshot(left: ViewportSnapshot | undefined, right: ViewportSnapshot): boolean {
  return left?.layoutHeight === right.layoutHeight
    && left.height === right.height
    && left.top === right.top
    && left.bottom === right.bottom;
}

export function useMemoViewport(enabled: boolean): CSSProperties | undefined {
  const [snapshot, setSnapshot] = useState<ViewportSnapshot>();

  useEffect(() => {
    if (!enabled) {
      setSnapshot(undefined);
      return undefined;
    }

    const visualViewport = window.visualViewport;
    let frameId: number | null = null;
    let settleTimer: number | null = null;

    const measure = () => {
      frameId = null;
      const next = readViewport();
      setSnapshot((current) => (sameSnapshot(current, next) ? current : next));
    };

    const scheduleMeasure = () => {
      if (frameId !== null) return;
      frameId = window.requestAnimationFrame(measure);
    };

    const scheduleSettleMeasure = () => {
      if (settleTimer !== null) window.clearTimeout(settleTimer);
      settleTimer = window.setTimeout(() => {
        settleTimer = null;
        scheduleMeasure();
      }, FOCUS_SETTLE_MS);
    };

    measure();
    window.addEventListener("resize", scheduleMeasure);
    window.addEventListener("orientationchange", scheduleMeasure);
    visualViewport?.addEventListener("resize", scheduleMeasure);
    visualViewport?.addEventListener("scroll", scheduleMeasure);
    document.addEventListener("focusout", scheduleSettleMeasure);

    return () => {
      if (frameId !== null) window.cancelAnimationFrame(frameId);
      if (settleTimer !== null) window.clearTimeout(settleTimer);
      window.removeEventListener("resize", scheduleMeasure);
      window.removeEventListener("orientationchange", scheduleMeasure);
      visualViewport?.removeEventListener("resize", scheduleMeasure);
      visualViewport?.removeEventListener("scroll", scheduleMeasure);
      document.removeEventListener("focusout", scheduleSettleMeasure);
    };
  }, [enabled]);

  return enabled && snapshot ? toViewportStyle(snapshot) : undefined;
}

export function useMemoMobileLayout(): boolean {
  const [isMobile, setIsMobile] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return undefined;

    const mediaQuery = window.matchMedia(MEMO_MOBILE_QUERY);
    const update = () => setIsMobile(mediaQuery.matches);

    update();
    mediaQuery.addEventListener?.("change", update);
    return () => mediaQuery.removeEventListener?.("change", update);
  }, []);

  return isMobile;
}
