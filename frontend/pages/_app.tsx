import "../styles/globals.css";
import "../styles/bootstrap-compat.css";
import "bootstrap-icons/font/bootstrap-icons.css";
import "../scripts/core/tooltip";
import "../scripts/core/alert_modal";
import "../scripts/core/csrf";
import type { AppProps } from "next/app";
import { Component, useEffect, useState, type ErrorInfo, type ReactNode } from "react";
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

export default function App({ Component, pageProps }: AppProps) {
  const router = useRouter();
  const showAiAgent = !AUTH_PAGES.has(router.pathname);
  const [isRouteTransitioning, setIsRouteTransitioning] = useState(false);

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

    const clearFinishTimer = () => {
      if (finishTimerId === null) return;
      window.clearTimeout(finishTimerId);
      finishTimerId = null;
    };
    const startTransition = () => {
      clearFinishTimer();
      setIsRouteTransitioning(true);
    };
    const finishTransition = () => {
      clearFinishTimer();
      finishTimerId = window.setTimeout(() => {
        setIsRouteTransitioning(false);
        finishTimerId = null;
      }, 140);
    };

    router.events.on("routeChangeStart", startTransition);
    router.events.on("routeChangeComplete", finishTransition);
    router.events.on("routeChangeError", finishTransition);

    return () => {
      clearFinishTimer();
      router.events.off("routeChangeStart", startTransition);
      router.events.off("routeChangeComplete", finishTransition);
      router.events.off("routeChangeError", finishTransition);
    };
  }, [router.events]);

  useEffect(() => {
    MENU_NAVIGATION_PATHS.forEach((path) => {
      void router.prefetch(path).catch(() => {
        // Prefetch is an optimization only; navigation still works without it.
      });
    });
  }, [router]);

  useEffect(() => {
    const handleMenuNavigation = (event: Event) => {
      const target = getMenuNavigationTarget((event as ChatCoreNavigationEvent).detail?.href);
      if (!target) return;

      event.preventDefault();
      if (target === router.asPath) return;

      setIsRouteTransitioning(true);
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
