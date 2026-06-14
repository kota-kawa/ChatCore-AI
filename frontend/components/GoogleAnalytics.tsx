import Script from "next/script";
import { useRouter } from "next/router";
import { useEffect } from "react";

// 環境変数からGA計測IDを取得（未設定時はデフォルト値を使用）
// Get GA measurement ID from env var (use default if not set)
const GA_MEASUREMENT_ID = process.env.NEXT_PUBLIC_GA_MEASUREMENT_ID || "G-Q1F9PY8BFJ";

declare global {
  interface Window {
    dataLayer?: unknown[];
    gtag?: (...args: unknown[]) => void;
  }
}

// 指定URLのページビューをGoogle Analyticsに送信する
// Send a page view event to Google Analytics for the given URL
function trackPageView(url: string) {
  if (!GA_MEASUREMENT_ID || typeof window.gtag !== "function") {
    return;
  }

  window.gtag("config", GA_MEASUREMENT_ID, {
    page_path: url
  });
}

// Next.jsのルーター遷移を検知してGoogle Analyticsにページビューを送信するコンポーネント
// Component that detects Next.js router transitions and sends page views to Google Analytics
export function GoogleAnalytics() {
  const router = useRouter();

  // ルーター遷移完了時にページビューを追跡するイベントリスナーを登録・解除する
  // Register/unregister event listener to track page views on route change complete
  useEffect(() => {
    if (!GA_MEASUREMENT_ID) {
      return undefined;
    }

    router.events.on("routeChangeComplete", trackPageView);

    return () => {
      router.events.off("routeChangeComplete", trackPageView);
    };
  }, [router.events]);

  // GA_MEASUREMENT_IDが未設定の場合は何もレンダリングしない
  // Render nothing if GA_MEASUREMENT_ID is not set
  if (!GA_MEASUREMENT_ID) {
    return null;
  }

  return (
    <>
      {/* GAのgtag.jsスクリプトを非同期で読み込む / Load gtag.js script asynchronously */}
      <Script
        src={`https://www.googletagmanager.com/gtag/js?id=${GA_MEASUREMENT_ID}`}
        strategy="afterInteractive"
      />
      {/* dataLayerとgtagを初期化するインラインスクリプト / Inline script to initialize dataLayer and gtag */}
      <Script id="google-analytics" strategy="afterInteractive">
        {`
          window.dataLayer = window.dataLayer || [];
          function gtag(){window.dataLayer.push(arguments);}
          window.gtag = gtag;
          gtag('js', new Date());
          gtag('config', '${GA_MEASUREMENT_ID}');
        `}
      </Script>
    </>
  );
}
