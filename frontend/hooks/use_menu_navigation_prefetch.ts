import { useEffect } from "react";
import type { NextRouter } from "next/router";

const BACKGROUND_QUIET_PERIOD_MS = 800;

// 初期ロードと入力が落ち着いた時間に一つずつ準備し、メニューを使う時はすぐ先読みする。
// Warm one route at a time after loading and input settle, and prepare immediately on menu intent.
export function useMenuNavigationPrefetch(
  router: Pick<NextRouter, "pathname" | "prefetch">,
  paths: readonly string[],
) {
  useEffect(() => {
    const requested = new Set<string>();
    const backgroundAttempted = new Set<string>();
    let disposed = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let idle: number | undefined;
    const cancelBackground = () => {
      clearTimeout(timer);
      if (idle !== undefined) window.cancelIdleCallback?.(idle);
      idle = undefined;
    };
    const prepare = async (path: string) => {
      if (path === router.pathname || requested.has(path)) return;
      requested.add(path);
      if (path === "/memo" && !document.querySelector('link[href="/memo/static/css/memo_form.css"]')) {
        const stylesheet = document.createElement("link");
        stylesheet.rel = "preload";
        stylesheet.setAttribute("as", "style");
        stylesheet.href = "/memo/static/css/memo_form.css";
        stylesheet.dataset.menuRouteStyle = "";
        document.head.append(stylesheet);
      }
      try {
        await router.prefetch(path);
      } catch {
        // A later menu interaction can retry; navigation does not depend on warming.
        requested.delete(path);
      }
    };
    const scheduleBackground = () => {
      cancelBackground();
      if (disposed || document.readyState !== "complete") return;
      timer = setTimeout(() => {
        const warmNext = () => {
          idle = undefined;
          if (disposed || !document.querySelector("action-menu, chat-action-menu")) return;
          const path = paths.find((candidate) => candidate !== router.pathname && !requested.has(candidate) && !backgroundAttempted.has(candidate));
          if (path) {
            backgroundAttempted.add(path);
            void prepare(path).then(scheduleBackground);
          }
        };
        if (window.requestIdleCallback) idle = window.requestIdleCallback(warmNext);
        else warmNext();
      }, BACKGROUND_QUIET_PERIOD_MS);
    };
    const onMenuIntent = (event: Event) => {
      const fromMenu = event.composedPath().some((target) =>
        target instanceof HTMLElement &&
        (target.localName === "action-menu" || target.localName === "chat-action-menu"),
      );
      if (!fromMenu) return;
      cancelBackground();
      for (const path of paths) {
        void prepare(path);
      }
    };

    scheduleBackground();
    window.addEventListener("load", scheduleBackground);
    document.addEventListener("input", scheduleBackground);
    document.addEventListener("keydown", scheduleBackground);
    document.addEventListener("pointerdown", scheduleBackground);
    document.addEventListener("pointerover", onMenuIntent);
    document.addEventListener("pointerdown", onMenuIntent);
    document.addEventListener("focusin", onMenuIntent);
    return () => {
      disposed = true;
      cancelBackground();
      window.removeEventListener("load", scheduleBackground);
      document.removeEventListener("input", scheduleBackground);
      document.removeEventListener("keydown", scheduleBackground);
      document.removeEventListener("pointerdown", scheduleBackground);
      document.removeEventListener("pointerover", onMenuIntent);
      document.removeEventListener("pointerdown", onMenuIntent);
      document.removeEventListener("focusin", onMenuIntent);
    };
  }, [paths, router]);
}
