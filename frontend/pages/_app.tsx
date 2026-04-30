import "../styles/globals.css";
import "../styles/bootstrap-compat.css";
import "bootstrap-icons/font/bootstrap-icons.css";
import "../scripts/core/tooltip";
import "../scripts/core/alert_modal";
import "../scripts/core/csrf";
import type { AppProps } from "next/app";
import { Component, useEffect, type ErrorInfo, type ReactNode } from "react";
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

export default function App({ Component, pageProps }: AppProps) {
  const router = useRouter();
  const showAiAgent = !AUTH_PAGES.has(router.pathname);

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

  return (
    <div className={appSansFont.variable}>
      <GlobalErrorBoundary>
        <GoogleAnalytics />
        <Component {...pageProps} />
        {showAiAgent && <GlobalAiAgent />}
      </GlobalErrorBoundary>
    </div>
  );
}
