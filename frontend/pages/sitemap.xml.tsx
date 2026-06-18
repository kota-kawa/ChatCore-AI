import type { GetServerSideProps } from "next";
import { resilientFetch } from "../scripts/core/resilient_fetch";

// Hostヘッダーの値を正規化する（配列の場合は先頭を取得）
// Normalize the Host header value (take the first if it's an array)
function normalizeHostHeader(header: string | string[] | undefined) {
  if (Array.isArray(header)) return header[0] || "";
  return header || "";
}

// X-Forwarded-Protoヘッダーを正規化する（カンマ区切りの最初の値を取得）
// Normalize the X-Forwarded-Proto header (take the first comma-separated value)
function normalizeProtoHeader(header: string | string[] | undefined) {
  const raw = Array.isArray(header) ? header[0] : header;
  if (!raw) return "";
  return raw.split(",")[0]?.trim() || "";
}

// XML属性・コンテンツをエスケープしてXXE/XMLインジェクションを防ぐ
// Escape XML attributes and content to prevent XXE/XML injection
function xmlEscape(value: string) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

// サイトマップに含める公開ルートの定義（変更頻度と優先度付き）
// Public route definitions included in the sitemap (with change frequency and priority)
export const PUBLIC_SITEMAP_ROUTES = [
  { path: "/", changefreq: "daily", priority: "1.0" },
  { path: "/prompt_share", changefreq: "daily", priority: "0.9" },
  { path: "/memo", changefreq: "weekly", priority: "0.5" }
] as const;

// 動的に追加するサイトマップ項目（個別の公開プロンプトページなど）の型
// Type for dynamically appended sitemap entries (e.g. individual public prompt pages)
export type SitemapRoute = {
  path: string;
  changefreq: string;
  priority: string;
  lastmod?: string;
};

// サイトマップに含める公開プロンプトの最大件数（巨大化を防ぐ上限）
// Maximum number of public prompts to include in the sitemap (cap to avoid bloat)
const MAX_PROMPT_ENTRIES = 5000;

// created_atをW3C準拠のISO8601文字列に正規化する（不正な値はundefinedにしてグローバルlastmodへフォールバック）
// Normalize created_at into a W3C-compliant ISO 8601 string (invalid values become undefined and fall back to the global lastmod)
function normalizeLastmod(value: string | undefined): string | undefined {
  if (!value) return undefined;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return undefined;
  return parsed.toISOString();
}

// バックエンドから公開プロンプト一覧を取得し、個別共有ページのサイトマップ項目を組み立てる
// Fetch the public prompt list from the backend and build sitemap entries for each shared page
async function fetchPublicPromptRoutes(): Promise<SitemapRoute[]> {
  const backendUrl = (process.env.BACKEND_URL || "http://localhost:5004").replace(/\/+$/, "");
  try {
    const response = await resilientFetch(`${backendUrl}/prompt_share/api/prompts`, {
      headers: { Accept: "application/json" }
    });
    if (!response.ok) return [];

    const data = (await response.json()) as { prompts?: Array<{ id?: string | number; created_at?: string }> };
    if (!Array.isArray(data.prompts)) return [];

    const routes: SitemapRoute[] = [];
    for (const prompt of data.prompts) {
      if (prompt.id === undefined || prompt.id === null || prompt.id === "") continue;
      // 末尾のスラッシュやXMLエスケープはbuildSitemapXml側で処理されるため、ここではパスのみ生成する
      // Only build the path here; trailing-slash handling and XML escaping happen in buildSitemapXml
      routes.push({
        path: `/shared/prompt/${encodeURIComponent(String(prompt.id))}`,
        changefreq: "weekly",
        priority: "0.6",
        lastmod: normalizeLastmod(prompt.created_at)
      });
      if (routes.length >= MAX_PROMPT_ENTRIES) break;
    }
    return routes;
  } catch {
    // 取得に失敗しても静的ルートのみでサイトマップを返す
    // Fall back to static routes only if fetching fails
    return [];
  }
}

// リクエストコンテキストからサイトのオリジンURLを解決する
// Resolve the site origin URL from the request context
function resolveOrigin(context: Parameters<GetServerSideProps>[0]) {
  const configuredOrigin =
    process.env.NEXT_PUBLIC_SITE_URL ||
    process.env.SITE_URL ||
    process.env.VERCEL_PROJECT_PRODUCTION_URL ||
    process.env.VERCEL_URL ||
    "";
  if (configuredOrigin) {
    const withProtocol = /^https?:\/\//i.test(configuredOrigin) ? configuredOrigin : `https://${configuredOrigin}`;
    return withProtocol.replace(/\/+$/, "");
  }

  const host = normalizeHostHeader(context.req.headers["x-forwarded-host"]) || normalizeHostHeader(context.req.headers.host);
  const proto = normalizeProtoHeader(context.req.headers["x-forwarded-proto"])
    || (process.env.NODE_ENV === "development" ? "http" : "https");
  return host ? `${proto}://${host}` : "";
}

// オリジンと最終更新日時からsitemap.xmlのXML文字列を組み立てる
// Build the sitemap.xml XML string from the origin and last modification date
export function buildSitemapXml(origin: string, lastmod: string, extraRoutes: readonly SitemapRoute[] = []) {
  const normalizedOrigin = origin.replace(/\/+$/, "");
  const routes: readonly (SitemapRoute | (typeof PUBLIC_SITEMAP_ROUTES)[number])[] = [
    ...PUBLIC_SITEMAP_ROUTES,
    ...extraRoutes
  ];
  const urls = routes
    .map((route) => {
      const loc = normalizedOrigin ? `${normalizedOrigin}${route.path}` : route.path;
      // 個別ルートにlastmodが指定されていればそれを優先する
      // Prefer a route-specific lastmod when provided
      const routeLastmod = ("lastmod" in route && route.lastmod) ? route.lastmod : lastmod;
      return [
        "  <url>",
        `    <loc>${xmlEscape(loc)}</loc>`,
        `    <lastmod>${xmlEscape(routeLastmod)}</lastmod>`,
        `    <changefreq>${route.changefreq}</changefreq>`,
        `    <priority>${route.priority}</priority>`,
        "  </url>"
      ].join("\n");
    })
    .join("\n");

  return [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    urls,
    "</urlset>",
    ""
  ].join("\n");
}

// sitemap.xmlをサーバーサイドで動的に生成して返すハンドラー
// Handler that dynamically generates and returns sitemap.xml on the server side
export const getServerSideProps: GetServerSideProps = async (context) => {
  const origin = resolveOrigin(context);
  const lastmod = new Date().toISOString();
  // 公開プロンプトの個別ページを動的に取得してサイトマップに追加する
  // Dynamically fetch individual public prompt pages and append them to the sitemap
  const promptRoutes = await fetchPublicPromptRoutes();
  const body = buildSitemapXml(origin, lastmod, promptRoutes);

  context.res.setHeader("Content-Type", "application/xml; charset=utf-8");
  context.res.setHeader("Cache-Control", "public, max-age=3600, s-maxage=3600");
  context.res.write(body);
  context.res.end();

  return { props: {} };
};

// Next.jsのページとしてエクスポートするが、コンテンツはgetServerSidePropsで直接出力するためnullを返す
// Exported as a Next.js page, but returns null since content is written directly in getServerSideProps
export default function SitemapXml() {
  return null;
}
