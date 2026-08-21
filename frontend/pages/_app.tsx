import "../styles/globals.css";
import "../styles/bootstrap-compat.css";
import "bootstrap-icons/font/bootstrap-icons.css";
import "../public/static/css/base/variables.css";
import "../public/static/css/base/animations.css";
import "../public/static/css/base/buttons.css";
import "../public/static/css/base/responsive.css";
import "../public/static/css/base/global.css";
import "../public/static/css/base/locale_transition.css";
import "../public/static/css/components/sidebar.css";
import "../public/static/css/components/prompt_assist.css";
import "../public/static/css/components/new_prompt_modal.css";
import "../public/static/css/components/prompt_category_select.css";
import "../public/static/css/components/streaming_text.css";
import "../public/static/css/components/alert_modal.css";
import "../public/static/css/components/copy_block.css";
import "../public/static/css/components/web_search_sources.css";
import "../public/static/css/components/setup_attach_menu.css";
import "../public/static/css/pages/chat/setup.css";
import "../public/static/css/pages/chat/chat_layout.css";
import "../public/static/css/pages/chat/chat_messages.css";
import "../public/static/css/pages/chat/chat_markdown.css";
import "../public/static/css/pages/chat/chat_input.css";
import "../public/static/css/pages/chat/tasks_order/tasks_order.css";
import "../public/static/css/pages/chat/tasks_order/task-edit-modal.css";
import "../public/static/css/pages/chat/project.css";
import "../public/static/css/pages/chat/index.css";
import "../public/memo/static/css/memo_form.css";
import "../public/prompt_share/static/css/base/base.css";
import "../public/prompt_share/static/css/pages/prompt_share.foundation.css";
import "../public/prompt_share/static/css/pages/prompt_share.cards-actions.css";
import "../public/prompt_share/static/css/pages/prompt_share.modals-composer.css";
import "../public/prompt_share/static/css/pages/prompt_share.ai-agent.css";
import "../public/prompt_share/static/css/pages/prompt_share.responsive.css";
import "../public/prompt_share/static/css/pages/prompt_share.button-system.css";
import "../public/prompt_share/static/css/pages/prompt_share.dark-mode.css";
import "../public/prompt_share/static/css/pages/prompt_manage.css";
import "../public/static/css/pages/user_settings/user_settings.css";
import "../public/static/css/pages/oauth_authorize/oauth_authorize.css";
import "../public/static/css/pages/shared_memo.css";
import "../public/static/css/pages/shared_prompt.css";
import "../public/static/css/pages/chat/shared_chat.css";
import "../scripts/core/tooltip";
import "../scripts/core/alert_modal";
import "../scripts/core/csrf";
import NextApp, { type AppContext, type AppProps } from "next/app";
import { Component, useEffect, type ErrorInfo, type ReactNode } from "react";
import { Noto_Sans_JP } from "next/font/google";
import { useRouter } from "next/router";
import { SWRConfig, useSWRConfig } from "swr";
import { GoogleAnalytics } from "../components/GoogleAnalytics";
import { GlobalAiAgent } from "../components/GlobalAiAgent";
import { NetworkStatusBanner } from "../components/NetworkStatusBanner";
import { applyTheme, getStoredThemePreference, resolveTheme, watchSystemTheme } from "../scripts/core/theme";
import { swrFetcher } from "../lib/data/swr_fetcher";
import { createPersistentCacheProvider, loadPersistentCacheEntries } from "../lib/data/persistent_cache";
import { LocaleProvider, useTranslation } from "../contexts/locale_context";
import { DEFAULT_LOCALE, normalizeLocale, resolvePageLocale, type Locale } from "../lib/i18n/config";

// アプリ全体のサンセリフフォント設定（CSS変数として提供）
// App-wide sans-serif font configuration (provided as a CSS variable)
const appSansFont = Noto_Sans_JP({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  display: "swap",
  variable: "--font-app-sans"
});

// グローバルエラーバウンダリーのprops・state型定義
// Props and state type definitions for the global error boundary
type GlobalErrorBoundaryProps = {
  children: ReactNode;
  messages: { heading: string; fallback: string; reload: string; unexpected: string };
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
      message: error instanceof Error ? error.message : ""
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
          <h1>{this.props.messages.heading}</h1>
          <p>{this.state.message || this.props.messages.fallback}</p>
          <button
            type="button"
            className="cc-texture-btn cc-texture-btn--danger"
            onClick={() => window.location.reload()}
          >
            {this.props.messages.reload}
          </button>
        </div>
      </main>
    );
  }
}

function LocalizedAppShell({ Component, pageProps, showAiAgent }: Pick<AppProps, "Component" | "pageProps"> & { showAiAgent: boolean }) {
  const { t } = useTranslation();
  return (
    <GlobalErrorBoundary messages={{
      heading: t("common.renderError"), fallback: t("common.reloadHelp"), reload: t("common.reload"), unexpected: t("common.unexpectedError")
    }}>
      <GoogleAnalytics />
      <NetworkStatusBanner />
      <Component {...pageProps} />
      {showAiAgent && <GlobalAiAgent />}
    </GlobalErrorBoundary>
  );
}

// 認証ページ（グローバルAIエージェントを非表示にするページ）のセット
// Set of auth pages (pages that hide the global AI agent)
const AUTH_PAGES = new Set(["/login", "/register", "/oauth/authorize"]);
// メニューナビゲーション対象のパス一覧
// Paths that are targets for menu navigation
const MENU_NAVIGATION_PATHS = ["/", "/memo", "/prompt_share"] as const;
const MENU_NAVIGATION_PATH_SET = new Set<string>(MENU_NAVIGATION_PATHS);

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

// 永続SWRキャッシュは初回クライアント描画では読まず、ReactがSSR HTMLを
// ハイドレートした後に反映する。これによりサーバーとクライアントの初期HTMLが
// 常に一致し、localStorage由来のハイドレーション不整合を防ぐ。
function PersistentCacheHydrator() {
  const { mutate } = useSWRConfig();

  useEffect(() => {
    for (const [key, data] of loadPersistentCacheEntries()) {
      void mutate(key, data, { revalidate: true });
    }
  }, [mutate]);

  return null;
}

// Next.jsのカスタムAppコンポーネント（テーマ管理と共通プロバイダーを統括する）
// Next.js custom App component (manages theme and shared providers)
type LocalizedPageProps = Record<string, unknown> & { __locale?: Locale };

export default function App({ Component, pageProps }: AppProps<LocalizedPageProps>) {
  const router = useRouter();
  // 認証ページではグローバルAIエージェントを非表示にする
  // Hide the global AI agent on auth pages
  const showAiAgent = !AUTH_PAGES.has(router.pathname);

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

  // メニューナビゲーション対象のルートを事前準備する
  // Pre-fetch menu navigation target routes
  useEffect(() => {
    MENU_NAVIGATION_PATHS.forEach((path) => {
      void router.prefetch(path).catch(() => {
        // Prefetch is an optimization only; navigation still works without it.
      });
    });
  }, [router]);

  // カスタムイベント「chatcore:navigate」をNext.jsルーターへ橋渡しする
  // Bridge the custom "chatcore:navigate" event to the Next.js router
  useEffect(() => {
    const handleMenuNavigation = (event: Event) => {
      const target = getMenuNavigationTarget((event as ChatCoreNavigationEvent).detail?.href);
      if (!target) return;

      event.preventDefault();
      // 同じパスへの遷移は無視する
      // Ignore navigation to the same path
      if (target === router.asPath) return;

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
    <LocaleProvider initialLocale={normalizeLocale(pageProps.__locale) ?? DEFAULT_LOCALE}>
      <SWRConfig value={swrGlobalConfig}>
        <PersistentCacheHydrator />
        <div className={appSansFont.variable}>
          <LocalizedAppShell Component={Component} pageProps={pageProps} showAiAgent={showAiAgent} />
        </div>
      </SWRConfig>
    </LocaleProvider>
  );
}

App.getInitialProps = async (appContext: AppContext) => {
  const appProps = await NextApp.getInitialProps(appContext);
  const request = appContext.ctx.req;
  // URLの言語をCookieやAccept-Languageより優先し、各正規URLの内容を安定させる。
  // Prefer the route locale over cookies and Accept-Language so each canonical URL
  // always serves one stable language.
  const locale = resolvePageLocale(
    appContext.ctx.locale,
    request?.headers.cookie,
    request?.headers["accept-language"]
  );
  return { ...appProps, pageProps: { ...appProps.pageProps, __locale: locale } };
};
