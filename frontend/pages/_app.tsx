import "../styles/globals.css";
import "../styles/bootstrap-compat.css";
import "bootstrap-icons/font/bootstrap-icons.css";
import "../scripts/core/tooltip";
import "../scripts/core/alert_modal";
import "../scripts/core/csrf";
import type { AppProps } from "next/app";
import { Component, useEffect, useRef, useState, type ErrorInfo, type ReactNode } from "react";
import { Noto_Sans_JP } from "next/font/google";
import { useRouter } from "next/router";
import { GoogleAnalytics } from "../components/GoogleAnalytics";
import { GlobalAiAgent } from "../components/GlobalAiAgent";
import { applyTheme, getStoredThemePreference, resolveTheme, watchSystemTheme } from "../scripts/core/theme";

const appSansFont = Noto_Sans_JP({
  subsets: ["latin"],
  weight: ["400", "500", "700"],
  display: "swap",
  variable: "--font-app-sans"
});

type GlobalErrorBoundaryProps = {
  children: ReactNode;
};

type GlobalErrorBoundaryState = {
  hasError: boolean;
  message: string;
};

class GlobalErrorBoundary extends Component<GlobalErrorBoundaryProps, GlobalErrorBoundaryState> {
  public constructor(props: GlobalErrorBoundaryProps) {
    super(props);
    this.state = {
      hasError: false,
      message: ""
    };
  }

  public static getDerivedStateFromError(error: unknown): GlobalErrorBoundaryState {
    return {
      hasError: true,
      message: error instanceof Error ? error.message : "予期しないエラーが発生しました。"
    };
  }

  public componentDidCatch(error: unknown, errorInfo: ErrorInfo) {
    console.error("Unhandled React rendering error:", error, errorInfo);
  }

  public render() {
    if (!this.state.hasError) {
      return this.props.children;
    }

    return (
      <main className="global-error-boundary" role="alert" aria-live="assertive">
        <div className="global-error-boundary__card">
          <h1>画面の表示中にエラーが発生しました。</h1>
          <p>{this.state.message || "お手数ですが、ページを再読み込みしてください。"}</p>
          <button
            type="button"
            className="cc-texture-btn cc-texture-btn--danger"
            onClick={() => window.location.reload()}
          >
            再読み込み
          </button>
        </div>
      </main>
    );
  }
}

const AUTH_PAGES = new Set(["/login", "/register"]);
const MENU_NAVIGATION_PATHS = ["/", "/memo", "/prompt_share"] as const;
const MENU_NAVIGATION_PATH_SET = new Set<string>(MENU_NAVIGATION_PATHS);
const ROUTE_STYLESHEETS_BY_PATH: Record<string, string[]> = {
  "/": ["/static/css/pages/chat/page.css"],
  "/memo": ["/memo/static/css/memo_form.css"],
  "/prompt_share": ["/prompt_share/static/css/pages/prompt_share.css"]
};
const ROUTE_REVEAL_DELAY_MS = 220;
const MENU_NAVIGATION_MIN_DELAY_MS = 120;
const STYLESHEET_PRELOAD_TIMEOUT_MS = 2200;
const stylesheetPreloadPromises = new Map<string, Promise<void>>();
const stylesheetApplyPromises = new Map<string, Promise<void>>();

type ChatCoreNavigationEvent = CustomEvent<{
  href?: string;
}>;

function getMenuNavigationTarget(rawHref: string | undefined) {
  if (!rawHref || typeof window === "undefined") return null;

  try {
    const url = new URL(rawHref, window.location.origin);
    if (url.origin !== window.location.origin || !MENU_NAVIGATION_PATH_SET.has(url.pathname)) {
      return null;
    }

    return `${url.pathname}${url.search}${url.hash}`;
  } catch {
    return null;
  }
}

function wait(ms: number) {
  return new Promise<void>((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

function getPathnameFromRouteUrl(rawUrl: string | undefined) {
  if (!rawUrl || typeof window === "undefined") return "";

  try {
    return new URL(rawUrl, window.location.origin).pathname;
  } catch {
    return "";
  }
}

function normalizeStylesheetHref(href: string) {
  return new URL(href, window.location.origin).href;
}

function isStylesheetApplied(absoluteHref: string) {
  const links = document.querySelectorAll<HTMLLinkElement>("link[rel='stylesheet']");
  return Array.from(links).some((link) => (
    link.href === absoluteHref && (link.dataset.ccRouteStylesheetReady === "true" || Boolean(link.sheet))
  ));
}

function ensureStylesheetPreloaded(href: string) {
  if (typeof window === "undefined") return Promise.resolve();

  const absoluteHref = normalizeStylesheetHref(href);
  if (isStylesheetApplied(absoluteHref)) return Promise.resolve();

  const cachedPromise = stylesheetPreloadPromises.get(absoluteHref);
  if (cachedPromise) return cachedPromise;

  const promise = new Promise<void>((resolve) => {
    const existingLink = Array.from(document.querySelectorAll<HTMLLinkElement>("link[href]")).find((candidate) => (
      candidate.href === absoluteHref || candidate.getAttribute("href") === href
    ));
    const link = existingLink || document.createElement("link");
    let didResolve = false;

    const cleanup = () => {
      link.removeEventListener("load", handleLoad);
      link.removeEventListener("error", handleLoad);
    };
    const handleLoad = () => {
      if (didResolve) return;
      didResolve = true;
      link.dataset.ccRouteStylesheetReady = "true";
      cleanup();
      resolve();
    };

    window.setTimeout(handleLoad, STYLESHEET_PRELOAD_TIMEOUT_MS);
    link.addEventListener("load", handleLoad, { once: true });
    link.addEventListener("error", handleLoad, { once: true });

    if (!existingLink) {
      link.rel = "preload";
      link.as = "style";
      link.href = href;
      link.dataset.ccRouteStylesheetPreload = "true";
      document.head.appendChild(link);
    }
  });

  stylesheetPreloadPromises.set(absoluteHref, promise);
  return promise;
}

function ensureStylesheetApplied(href: string) {
  if (typeof window === "undefined") return Promise.resolve();

  const absoluteHref = normalizeStylesheetHref(href);
  if (isStylesheetApplied(absoluteHref)) return Promise.resolve();

  const cachedPromise = stylesheetApplyPromises.get(absoluteHref);
  if (cachedPromise) return cachedPromise;

  const promise = new Promise<void>((resolve) => {
    const existingStylesheet = Array.from(document.querySelectorAll<HTMLLinkElement>("link[rel='stylesheet'][href]")).find((candidate) => (
      candidate.href === absoluteHref || candidate.getAttribute("href") === href
    ));
    const link = existingStylesheet || document.createElement("link");
    let didResolve = false;

    const cleanup = () => {
      link.removeEventListener("load", handleLoad);
      link.removeEventListener("error", handleLoad);
    };
    const handleLoad = () => {
      if (didResolve) return;
      didResolve = true;
      link.dataset.ccRouteStylesheetReady = "true";
      cleanup();
      resolve();
    };

    window.setTimeout(handleLoad, STYLESHEET_PRELOAD_TIMEOUT_MS);
    link.addEventListener("load", handleLoad, { once: true });
    link.addEventListener("error", handleLoad, { once: true });

    if (link.sheet) {
      handleLoad();
      return;
    }

    if (!existingStylesheet) {
      link.rel = "stylesheet";
      link.href = href;
      link.dataset.ccRouteStylesheetInjected = "true";
      document.head.appendChild(link);
    }
  });

  stylesheetApplyPromises.set(absoluteHref, promise);
  return promise;
}

function ensureRouteStylesheetsPreloaded(pathname: string) {
  const stylesheetHrefs = ROUTE_STYLESHEETS_BY_PATH[pathname] || [];
  if (stylesheetHrefs.length === 0) return Promise.resolve();

  return Promise.all(stylesheetHrefs.map(ensureStylesheetPreloaded)).then(() => undefined);
}

function ensureRouteStylesheetsApplied(pathname: string) {
  const stylesheetHrefs = ROUTE_STYLESHEETS_BY_PATH[pathname] || [];
  if (stylesheetHrefs.length === 0) return Promise.resolve();

  return Promise.all(stylesheetHrefs.map(ensureStylesheetApplied)).then(() => undefined);
}

export default function App({ Component, pageProps }: AppProps) {
  const router = useRouter();
  const showAiAgent = !AUTH_PAGES.has(router.pathname);
  const [isRouteTransitioning, setIsRouteTransitioning] = useState(false);
  const navigationRequestIdRef = useRef(0);

  useEffect(() => {
    const reapplyTheme = () => {
      applyTheme(resolveTheme(getStoredThemePreference()));
    };

    reapplyTheme();
    watchSystemTheme();

    const onPageShow = (event: PageTransitionEvent) => {
      if (event.persisted) {
        reapplyTheme();
      }
    };
    const onStorage = (event: StorageEvent) => {
      if (event.key === null || event.key === "chatcore-theme") {
        reapplyTheme();
      }
    };

    window.addEventListener("pageshow", onPageShow);
    window.addEventListener("storage", onStorage);

    return () => {
      window.removeEventListener("pageshow", onPageShow);
      window.removeEventListener("storage", onStorage);
    };
  }, []);

  useEffect(() => {
    let finishTimerId: number | null = null;
    let finishRequestId = 0;

    const clearFinishTimer = () => {
      if (finishTimerId === null) return;
      window.clearTimeout(finishTimerId);
      finishTimerId = null;
    };
    const startTransition = () => {
      clearFinishTimer();
      finishRequestId += 1;
      setIsRouteTransitioning(true);
    };
    const finishTransition = (url?: string) => {
      clearFinishTimer();
      const currentFinishRequestId = ++finishRequestId;
      void Promise.all([
        ensureRouteStylesheetsApplied(getPathnameFromRouteUrl(url)),
        wait(ROUTE_REVEAL_DELAY_MS)
      ]).finally(() => {
        if (currentFinishRequestId !== finishRequestId) return;
        setIsRouteTransitioning(false);
      });
    };
    const cancelTransition = () => {
      clearFinishTimer();
      finishRequestId += 1;
      finishTimerId = window.setTimeout(() => {
        setIsRouteTransitioning(false);
        finishTimerId = null;
      }, ROUTE_REVEAL_DELAY_MS);
    };

    router.events.on("routeChangeStart", startTransition);
    router.events.on("routeChangeComplete", finishTransition);
    router.events.on("routeChangeError", cancelTransition);

    return () => {
      clearFinishTimer();
      router.events.off("routeChangeStart", startTransition);
      router.events.off("routeChangeComplete", finishTransition);
      router.events.off("routeChangeError", cancelTransition);
    };
  }, [router.events]);

  useEffect(() => {
    MENU_NAVIGATION_PATHS.forEach((path) => {
      void router.prefetch(path).catch(() => {
        // Prefetch is an optimization only; navigation still works without it.
      });
      void ensureRouteStylesheetsPreloaded(path);
    });
  }, [router]);

  useEffect(() => {
    const handleMenuNavigation = async (event: Event) => {
      const target = getMenuNavigationTarget((event as ChatCoreNavigationEvent).detail?.href);
      if (!target) return;

      event.preventDefault();
      if (target === router.asPath) return;

      const currentNavigationRequestId = navigationRequestIdRef.current + 1;
      navigationRequestIdRef.current = currentNavigationRequestId;
      setIsRouteTransitioning(true);
      await Promise.all([
        ensureRouteStylesheetsPreloaded(getPathnameFromRouteUrl(target)),
        wait(MENU_NAVIGATION_MIN_DELAY_MS)
      ]);
      if (currentNavigationRequestId !== navigationRequestIdRef.current) return;

      void router.push(target).catch(() => {
        window.location.href = target;
      });
    };

    window.addEventListener("chatcore:navigate", handleMenuNavigation);
    return () => {
      window.removeEventListener("chatcore:navigate", handleMenuNavigation);
    };
  }, [router]);

  return (
    <div className={`${appSansFont.variable}${isRouteTransitioning ? " is-route-transitioning" : ""}`}>
      <GlobalErrorBoundary>
        <GoogleAnalytics />
        <div className="cc-route-frame">
          <Component {...pageProps} />
        </div>
        <div className="cc-route-transition-overlay" aria-hidden="true">
          <div className="cc-route-transition-overlay__bar"></div>
        </div>
        {showAiAgent && <GlobalAiAgent />}
      </GlobalErrorBoundary>
    </div>
  );
}
