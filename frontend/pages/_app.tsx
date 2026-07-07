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
import { SWRConfig } from "swr";
import { GoogleAnalytics } from "../components/GoogleAnalytics";
import { GlobalAiAgent } from "../components/GlobalAiAgent";
import { NetworkStatusBanner } from "../components/NetworkStatusBanner";
import { applyTheme, getStoredThemePreference, resolveTheme, watchSystemTheme } from "../scripts/core/theme";
import { swrFetcher } from "../lib/data/swr_fetcher";
import { createPersistentCacheProvider } from "../lib/data/persistent_cache";
import { getAllRouteStylesheetHrefs, getRouteStylesheetHrefs } from "../lib/route_stylesheets";

// アプリ全体のサンセリフフォント設定（CSS変数として提供）
// App-wide sans-serif font configuration (provided as a CSS variable)
const appSansFont = Noto_Sans_JP({
  subsets: ["latin"],
  weight: ["400", "500", "700"],
  display: "swap",
  variable: "--font-app-sans"
});

// グローバルエラーバウンダリーのprops・state型定義
// Props and state type definitions for the global error boundary
type GlobalErrorBoundaryProps = {
  children: ReactNode;
};

type GlobalErrorBoundaryState = {
  hasError: boolean;
  message: string;
};

// ReactのレンダリングエラーをキャッチしてフォールバックUIを表示するクラスコンポーネント
// Class component that catches React rendering errors and displays a fallback UI
class GlobalErrorBoundary extends Component<GlobalErrorBoundaryProps, GlobalErrorBoundaryState> {
  public constructor(props: GlobalErrorBoundaryProps) {
    super(props);
    this.state = {
      hasError: false,
      message: ""
    };
  }

  // エラー発生時にエラーメッセージをstateに保存する（staticメソッドのため副作用なし）
  // Save the error message to state when an error occurs (no side effects as it's a static method)
  public static getDerivedStateFromError(error: unknown): GlobalErrorBoundaryState {
    return {
      hasError: true,
      message: error instanceof Error ? error.message : "予期しないエラーが発生しました。"
    };
  }

  // エラーをコンソールに記録する（モニタリングサービスへの送信もここで行う）
  // Log the error to the console (also send to monitoring service here if needed)
  public componentDidCatch(error: unknown, errorInfo: ErrorInfo) {
    console.error("Unhandled React rendering error:", error, errorInfo);
  }

  public render() {
    if (!this.state.hasError) {
      return this.props.children;
    }

    // エラー発生時はリロードボタン付きのエラー画面を表示する
    // Display an error screen with a reload button when an error occurs
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

// 認証ページ（グローバルAIエージェントを非表示にするページ）のセット
// Set of auth pages (pages that hide the global AI agent)
const AUTH_PAGES = new Set(["/login", "/register"]);
// メニューナビゲーション対象のパス一覧
// Paths that are targets for menu navigation
const MENU_NAVIGATION_PATHS = ["/", "/memo", "/prompt_share"] as const;
const MENU_NAVIGATION_PATH_SET = new Set<string>(MENU_NAVIGATION_PATHS);
// ルート遷移後にコンテンツを表示するまでの最小遅延（スタイルシートが揃うまで待つ）
// Minimum delay before showing content after route transition (wait for stylesheets)
const ROUTE_REVEAL_DELAY_MS = 220;
// メニューナビゲーション時の最小遅延（ちらつきを防ぐ）
// Minimum delay for menu navigation (prevents flickering)
const MENU_NAVIGATION_MIN_DELAY_MS = 120;
// スタイルシートのプリロードタイムアウト（ネットワークが遅い環境でもブロックしない）
// Stylesheet preload timeout (to avoid blocking in slow network environments)
const STYLESHEET_PRELOAD_TIMEOUT_MS = 2200;
// プリロード中・適用中のスタイルシートをキャッシュするMap（重複リクエストを防ぐ）
// Maps caching in-progress preload/apply promises (prevents duplicate requests)
const stylesheetPreloadPromises = new Map<string, Promise<void>>();
const stylesheetApplyPromises = new Map<string, Promise<void>>();

// メニューナビゲーションカスタムイベントの型定義
// Type definition for the menu navigation custom event
type ChatCoreNavigationEvent = CustomEvent<{
  href?: string;
}>;

// メニューナビゲーションのターゲットパスを検証して返す（不正なオリジンや対象外パスはnull）
// Validate and return the menu navigation target path (returns null for invalid origins or non-target paths)
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

// 指定時間後に解決するPromiseを返すユーティリティ
// Utility that returns a Promise that resolves after the specified duration
function wait(ms: number) {
  return new Promise<void>((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

// ルートURLからpathnameを抽出するユーティリティ
// Utility to extract the pathname from a route URL
function getPathnameFromRouteUrl(rawUrl: string | undefined) {
  if (!rawUrl || typeof window === "undefined") return "";

  try {
    return new URL(rawUrl, window.location.origin).pathname;
  } catch {
    return "";
  }
}

// CSSのhrefを絶対URLに正規化する
// Normalize a CSS href to an absolute URL
function normalizeStylesheetHref(href: string) {
  return new URL(href, window.location.origin).href;
}

// 指定のスタイルシートがすでにDOMに適用済みかどうかを確認する
// Check if the specified stylesheet is already applied in the DOM
function isStylesheetApplied(absoluteHref: string) {
  const links = document.querySelectorAll<HTMLLinkElement>("link[rel='stylesheet']");
  return Array.from(links).some((link) => (
    link.href === absoluteHref && (link.dataset.ccRouteStylesheetReady === "true" || Boolean(link.sheet))
  ));
}

// スタイルシートをpreloadリンクとして先読みする（適用はしない）
// Preload a stylesheet as a preload link (does not apply it yet)
function ensureStylesheetPreloaded(href: string) {
  if (typeof window === "undefined") return Promise.resolve();

  const absoluteHref = normalizeStylesheetHref(href);
  if (isStylesheetApplied(absoluteHref)) return Promise.resolve();

  // すでにプリロード中なら同じPromiseを返す
  // Return the same Promise if already preloading
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

    // タイムアウトを設定してネットワークエラー時でも解決する
    // Set timeout to resolve even on network error
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

// スタイルシートをDOMに適用する（未適用の場合は<link rel="stylesheet">を追加する）
// Apply a stylesheet to the DOM (add <link rel="stylesheet"> if not already applied)
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
    } else if (link.rel === "preload") {
      // プリロード済みリンクを再利用するときは、遷移先のCSSとして適用する。
      // When reusing a preloaded link, promote it to the stylesheet for the destination route.
      link.rel = "stylesheet";
      link.removeAttribute("as");
      link.dataset.ccRouteStylesheetInjected = "true";
    }
  });

  stylesheetApplyPromises.set(absoluteHref, promise);
  return promise;
}

// 指定パスに必要なすべてのスタイルシートをプリロードする
// Preload all stylesheets required for the specified path
function ensureRouteStylesheetsPreloaded(pathname: string) {
  const stylesheetHrefs = getRouteStylesheetHrefs(pathname);
  if (stylesheetHrefs.length === 0) return Promise.resolve();

  return Promise.all(stylesheetHrefs.map(ensureStylesheetPreloaded)).then(() => undefined);
}

// 指定パスに必要なすべてのスタイルシートをDOMに適用する
// Apply all stylesheets required for the specified path to the DOM
function ensureRouteStylesheetsApplied(pathname: string) {
  const stylesheetHrefs = getRouteStylesheetHrefs(pathname);
  if (stylesheetHrefs.length === 0) {
    removeInactiveRouteStylesheets(pathname);
    return Promise.resolve();
  }

  return Promise.all(stylesheetHrefs.map(ensureStylesheetApplied)).then(() => {
    removeInactiveRouteStylesheets(pathname);
  });
}


// 現在のルートで不要になった、遅延適用済みのルート専用CSSを取り除く
// Remove lazily-applied route-specific CSS that is no longer needed for the current route
function removeInactiveRouteStylesheets(activePathname: string) {
  if (typeof window === "undefined") return;

  const activeHrefs = new Set(getRouteStylesheetHrefs(activePathname).map(normalizeStylesheetHref));
  const routeHrefs = new Set(getAllRouteStylesheetHrefs().map(normalizeStylesheetHref));

  document.querySelectorAll<HTMLLinkElement>("link[data-cc-route-stylesheet-injected='true'][href]").forEach((link) => {
    if (!routeHrefs.has(link.href) || activeHrefs.has(link.href)) return;
    link.remove();
    stylesheetApplyPromises.delete(link.href);
  });
}

// localStorage バックの SWR キャッシュプロバイダーは一度だけ生成する（再生成するとキャッシュが失われる）。
// Create the localStorage-backed SWR cache provider once (re-creating it would drop the cache).
const persistentCacheProvider = createPersistentCacheProvider();

// アプリ全体の SWR 既定設定。遅い回線でも前回データを即表示し、再接続・フォーカスで裏更新する。
// App-wide SWR defaults: show previous data instantly on slow links and revalidate on reconnect/focus.
const swrGlobalConfig = {
  fetcher: swrFetcher,
  provider: persistentCacheProvider,
  keepPreviousData: true,
  dedupingInterval: 4000,
  revalidateOnReconnect: true,
  focusThrottleInterval: 8000,
  errorRetryCount: 2,
} as const;

// Next.jsのカスタムAppコンポーネント（テーマ管理・ルート遷移・スタイルシート先読みを統括する）
// Next.js custom App component (manages theme, route transitions, and stylesheet preloading)
export default function App({ Component, pageProps }: AppProps) {
  const router = useRouter();
  // 認証ページではグローバルAIエージェントを非表示にする
  // Hide the global AI agent on auth pages
  const showAiAgent = !AUTH_PAGES.has(router.pathname);
  const [isRouteTransitioning, setIsRouteTransitioning] = useState(false);
  // 並行したナビゲーションリクエストを識別するIDのref（古いリクエストを無視するため）
  // Ref for identifying concurrent navigation requests (to ignore stale requests)
  const navigationRequestIdRef = useRef(0);

  useEffect(() => {
    (window as Window & { __CHAT_CORE_APP_HYDRATED__?: boolean }).__CHAT_CORE_APP_HYDRATED__ = true;
  }, []);

  // テーマの初期化とストレージ変更・ページ表示イベントへの同期
  // Initialize the theme and sync on storage changes and page show events
  useEffect(() => {
    const reapplyTheme = () => {
      applyTheme(resolveTheme(getStoredThemePreference()));
    };

    reapplyTheme();
    watchSystemTheme();

    const onPageShow = (event: PageTransitionEvent) => {
      // bfcacheから復元した場合もテーマを再適用する
      // Re-apply the theme when restored from bfcache
      if (event.persisted) {
        reapplyTheme();
      }
    };
    const onStorage = (event: StorageEvent) => {
      // 別タブでテーマが変更されたらこのタブにも反映する
      // Reflect theme changes from other tabs to this tab
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

  // ルーターイベントに応じてルート遷移状態を管理し、スタイルシートが揃うまで待機する
  // Manage route transition state based on router events and wait until stylesheets are ready
  useEffect(() => {
    let finishTimerId: number | null = null;
    let finishRequestId = 0;

    const clearFinishTimer = () => {
      if (finishTimerId === null) return;
      window.clearTimeout(finishTimerId);
      finishTimerId = null;
    };
    // 遷移開始：ローディング状態に設定し、遷移先のCSSの先読みを開始する
    // Transition start: set to loading state and start preloading the destination CSS
    const startTransition = (url?: string) => {
      clearFinishTimer();
      finishRequestId += 1;
      setIsRouteTransitioning(true);
      // ページ描画を待たずにダウンロードを開始して、遷移完了時までにCSSを揃える
      // Start the download without waiting for the page render so the CSS is ready by transition end
      void ensureRouteStylesheetsPreloaded(getPathnameFromRouteUrl(url));
    };
    // 遷移完了：スタイルシートの適用と最小遅延を待ってからローディングを解除する
    // Transition complete: wait for stylesheet application and minimum delay before releasing loading state
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
    // 遷移キャンセル：短い遅延後にローディングを解除する
    // Transition cancel: release loading state after a short delay
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

  // メニューナビゲーション対象のルートをプリフェッチとスタイルシートプリロードで事前準備する
  // Pre-fetch and pre-load stylesheets for menu navigation target routes
  useEffect(() => {
    MENU_NAVIGATION_PATHS.forEach((path) => {
      void router.prefetch(path).catch(() => {
        // Prefetch is an optimization only; navigation still works without it.
      });
      void ensureRouteStylesheetsPreloaded(path);
    });
  }, [router]);

  // カスタムイベント「chatcore:navigate」を処理し、スタイルシートが揃ってからナビゲーションを実行する
  // Handle the custom event "chatcore:navigate" and navigate after stylesheets are ready
  useEffect(() => {
    const handleMenuNavigation = async (event: Event) => {
      const target = getMenuNavigationTarget((event as ChatCoreNavigationEvent).detail?.href);
      if (!target) return;

      event.preventDefault();
      // 同じパスへの遷移は無視する
      // Ignore navigation to the same path
      if (target === router.asPath) return;

      const currentNavigationRequestId = navigationRequestIdRef.current + 1;
      navigationRequestIdRef.current = currentNavigationRequestId;
      setIsRouteTransitioning(true);
      await Promise.all([
        ensureRouteStylesheetsPreloaded(getPathnameFromRouteUrl(target)),
        wait(MENU_NAVIGATION_MIN_DELAY_MS)
      ]);
      // 後続のナビゲーションリクエストによって上書きされた場合は無視する
      // Ignore if overridden by a subsequent navigation request
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
    <SWRConfig value={swrGlobalConfig}>
      <div className={`${appSansFont.variable}${isRouteTransitioning ? " is-route-transitioning" : ""}`}>
        <GlobalErrorBoundary>
          <GoogleAnalytics />
          {/* オフライン・低速回線・復帰を控えめに通知する / Subtly announce offline/slow/recovery */}
          <NetworkStatusBanner />
          {/* ルート遷移アニメーション中にオーバーレイを表示する / Show overlay during route transition animation */}
          <div className="cc-route-frame">
            <Component {...pageProps} />
          </div>
          <div className="cc-route-transition-overlay" aria-hidden="true">
            <div className="cc-route-transition-overlay__bar"></div>
          </div>
          {/* 認証ページ以外でグローバルAIエージェントを表示する / Show global AI agent on non-auth pages */}
          {showAiAgent && <GlobalAiAgent />}
        </GlobalErrorBoundary>
      </div>
    </SWRConfig>
  );
}
