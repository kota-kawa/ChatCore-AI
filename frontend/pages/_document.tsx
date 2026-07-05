import { Html, Head, Main, NextScript } from "next/document";

// フラッシュを防ぐために<head>内で同期的にテーマを適用するインラインスクリプト
// Inline script to synchronously apply the theme in <head> to prevent flash
const themeBootstrapScript = `(function(){try{var k='chatcore-theme';var v=localStorage.getItem(k);if(v!=='dark'&&v!=='light'){v=window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';}document.documentElement.setAttribute('data-theme',v);}catch(e){document.documentElement.setAttribute('data-theme','light');}})();`;

// トップページ再読込時、直前がチャット画面ならハイドレーション前に <html> へ
// フラグを立て、CSS でセットアップ画面の一瞬の表示（フラッシュ）を防ぐ。
// フラグはビュー復元完了後に use_home_page_controller が解除する。
// キーは frontend/scripts/core/constants.ts の STORAGE_KEYS.homePageViewState と同一。
// On home-page reloads, when the last view was the chat view, set a flag on
// <html> before hydration so CSS can prevent the setup view from flashing.
// The flag is cleared by use_home_page_controller once the view is restored.
// The key must match STORAGE_KEYS.homePageViewState in frontend/scripts/core/constants.ts.
const homeViewBootstrapScript = `(function(){try{if(location.pathname!=='/')return;var shouldBootChat=localStorage.getItem('chatcore.home.viewState')==='chat';if(!shouldBootChat){try{var raw=localStorage.getItem('chatcore.chat.activeGeneration');var parsed=raw?JSON.parse(raw):null;var updatedAt=Number(parsed&&parsed.updatedAt);shouldBootChat=!!(parsed&&typeof parsed.roomId==='string'&&parsed.roomId.trim()&&isFinite(updatedAt)&&Date.now()-updatedAt<=1800000);}catch(_){}}if(shouldBootChat){document.documentElement.setAttribute('data-cc-home-boot-view','chat');}}catch(e){}})();`;

// Next.jsカスタムDocumentコンポーネント（共通のHTMLシェルとPWA対応のmeta/linkタグを設定する）
// Next.js custom Document component (sets up the common HTML shell and PWA-related meta/link tags)
export default function Document() {
  return (
    <Html lang="ja">
      <Head>
        {/* カラースキームとテーマカラーの設定 / Color scheme and theme color settings */}
        <meta name="color-scheme" content="light dark" />
        <meta name="theme-color" content="#ffffff" media="(prefers-color-scheme: light)" />
        <meta name="theme-color" content="#0f172a" media="(prefers-color-scheme: dark)" />
        {/* PWA関連のmeta設定 / PWA-related meta settings */}
        <meta name="mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="default" />
        <meta name="apple-mobile-web-app-title" content="Chat Core" />
        <link rel="manifest" href="/manifest.json" />
        <link rel="apple-touch-icon" href="/static/apple-touch-icon.png" />
        {/* テーマをFOUCなしで適用するためのブートストラップスクリプト / Bootstrap script to apply theme without FOUC */}
        <script dangerouslySetInnerHTML={{ __html: themeBootstrapScript }} />
        {/* チャット画面復元時のセットアップ画面フラッシュを防ぐブートストラップスクリプト / Bootstrap script that prevents the setup view from flashing when restoring the chat view */}
        <script dangerouslySetInnerHTML={{ __html: homeViewBootstrapScript }} />
      </Head>
      <body className="min-h-screen font-sans antialiased">
        <Main />
        <NextScript />
      </body>
    </Html>
  );
}
