import type { GetServerSideProps } from "next";

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

// robots.txtをサーバーサイドで動的に生成して返すハンドラー
// Handler that dynamically generates and returns robots.txt on the server side
export const getServerSideProps: GetServerSideProps = async (context) => {
  // 環境変数またはリクエストヘッダーからサイトのオリジンを解決する
  // Resolve the site origin from environment variables or request headers
  const configuredOrigin =
    process.env.NEXT_PUBLIC_SITE_URL ||
    process.env.SITE_URL ||
    process.env.VERCEL_PROJECT_PRODUCTION_URL ||
    process.env.VERCEL_URL ||
    "";
  const host = normalizeHostHeader(context.req.headers["x-forwarded-host"]) || normalizeHostHeader(context.req.headers.host);
  const proto = normalizeProtoHeader(context.req.headers["x-forwarded-proto"])
    || (process.env.NODE_ENV === "development" ? "http" : "https");
  const requestOrigin = host ? `${proto}://${host}` : "";
  const origin = (configuredOrigin
    ? (/^https?:\/\//i.test(configuredOrigin) ? configuredOrigin : `https://${configuredOrigin}`)
    : requestOrigin).replace(/\/+$/, "");

  const body = buildRobotsTxt(origin);

  context.res.setHeader("Content-Type", "text/plain; charset=utf-8");
  context.res.setHeader("Cache-Control", "public, max-age=3600, s-maxage=3600");
  context.res.write(body);
  context.res.end();

  return { props: {} };
};

// オリジンURLを受け取ってrobots.txtの内容を組み立てる
// Build the robots.txt content from the given origin URL
export function buildRobotsTxt(origin: string) {
  return [
    "User-agent: *",
    "Allow: /",
    // APIエンドポイントはクローラーから除外する
    // Exclude API endpoints from crawlers
    "Disallow: /api/",
    "Disallow: /admin/api/",
    "Disallow: /memo/api/",
    "Disallow: /prompt_manage/api/",
    "Disallow: /prompt_share/api/",
    "Disallow: /search/",
    "",
    `Sitemap: ${origin ? `${origin}/sitemap.xml` : "/sitemap.xml"}`,
    ""
  ].join("\n");
}

// Next.jsのページとしてエクスポートするが、コンテンツはgetServerSidePropsで直接出力するためnullを返す
// Exported as a Next.js page, but returns null since content is written directly in getServerSideProps
export default function RobotsTxt() {
  return null;
}
