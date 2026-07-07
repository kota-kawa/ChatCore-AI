// ルート(pathname)ごとに必要なページ専用CSSを解決するモジュール。
// クライアントサイド遷移では next/head の <link rel="stylesheet"> が
// ページ描画後に読み込まれるため、ここで宣言したCSSを _app が
// 遷移開始時に先読みし、読み込み完了までページの表示を遅らせることで
// スタイル未適用のコンテンツ(FOUC)が見えるのを防ぐ。
// Resolves the page-specific CSS required for each route (pathname).
// During client-side navigation, <link rel="stylesheet"> tags in next/head
// only start loading after the page renders, so _app preloads the CSS
// declared here when a transition starts and delays revealing the page
// until it has loaded, preventing a flash of unstyled content (FOUC).

type RouteStylesheetRule = {
  pattern: RegExp;
  hrefs: string[];
};

// 動的セグメントを含むルートは正規表現でマッチさせる（先勝ち）。
// より具体的なパターンを先に並べること。
// Routes with dynamic segments are matched via RegExp (first match wins).
// Keep more specific patterns first.
const ROUTE_STYLESHEET_RULES: RouteStylesheetRule[] = [
  { pattern: /^\/$/, hrefs: ["/static/css/pages/chat/page.css"] },
  { pattern: /^\/memo$/, hrefs: ["/memo/static/css/memo_form.css"] },
  { pattern: /^\/prompt_share$/, hrefs: ["/prompt_share/static/css/pages/prompt_share.css"] },
  { pattern: /^\/prompt_share\/manage_prompts$/, hrefs: ["/prompt_share/static/css/pages/prompt_manage.css"] },
  { pattern: /^\/settings$/, hrefs: ["/static/css/pages/user_settings/index.css"] },
  { pattern: /^\/shared\/memo\/[^/]+$/, hrefs: ["/static/css/pages/shared_memo.css"] },
  { pattern: /^\/shared\/prompt\/[^/]+(?:\/.*)?$/, hrefs: ["/static/css/pages/shared_prompt.css"] },
  { pattern: /^\/shared\/[^/]+$/, hrefs: ["/static/css/pages/chat/shared_chat.css"] },
];

// 指定pathnameに必要なページ専用CSSのhref一覧を返す（該当なしは空配列）
// Return the page-specific CSS hrefs required for the pathname (empty array if none)
export function getRouteStylesheetHrefs(pathname: string): string[] {
  const rule = ROUTE_STYLESHEET_RULES.find((candidate) => candidate.pattern.test(pathname));
  return rule ? [...rule.hrefs] : [];
}

// すべてのルート専用CSSのhref一覧（遷移後の不要CSS掃除に使う）
// All route-specific CSS hrefs (used to clean up stale CSS after navigation)
export function getAllRouteStylesheetHrefs(): string[] {
  return ROUTE_STYLESHEET_RULES.flatMap((rule) => rule.hrefs);
}
