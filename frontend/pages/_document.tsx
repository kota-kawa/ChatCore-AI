import { Html, Head, Main, NextScript } from "next/document";

const themeBootstrapScript = `(function(){try{var k='chatcore-theme';var v=localStorage.getItem(k);if(v!=='dark'&&v!=='light'){v=window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';}document.documentElement.setAttribute('data-theme',v);}catch(e){document.documentElement.setAttribute('data-theme','light');}})();`;

export default function Document() {
  return (
    <Html lang="ja">
      <Head>
        <meta name="color-scheme" content="light dark" />
        <meta name="theme-color" content="#ffffff" media="(prefers-color-scheme: light)" />
        <meta name="theme-color" content="#0f172a" media="(prefers-color-scheme: dark)" />
        <meta name="mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="default" />
        <meta name="apple-mobile-web-app-title" content="Chat Core" />
        <link rel="manifest" href="/manifest.json" />
        <link rel="apple-touch-icon" href="/static/apple-touch-icon.png" />
        <script dangerouslySetInnerHTML={{ __html: themeBootstrapScript }} />
      </Head>
      <body className="min-h-screen font-sans antialiased">
        <Main />
        <NextScript />
      </body>
    </Html>
  );
}
