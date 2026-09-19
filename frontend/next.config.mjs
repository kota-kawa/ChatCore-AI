const backendUrl = process.env.BACKEND_URL || "http://localhost:5004";
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
  async headers() {
    return [
      {
        source: "/:path*",
        headers: securityHeaders
      }
    ];
  },
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
