// /robots.txt をSSRで動的に生成するページ。サイトのオリジンを環境変数かリクエストヘッダーから解決し、sitemap.xml の場所を含めて返す。
// Page that generates /robots.txt dynamically at SSR; resolves the site origin from env vars or request headers and points to sitemap.xml.
import type { GetServerSideProps } from "next";
import { getRequestOrigin } from "../lib/server/request_origin";

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
  const requestOrigin = getRequestOrigin(context.req);
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
    // 作例画像はAPI配下で配信されるが、og:imageと構造化データのimageが指す実体なので
    // API全体のブロックから除外する（画像検索とリッチリザルトで参照させる）。
    // Reference images are served under the API prefix, yet they are what og:image and the
    // structured-data image point at, so exempt them from the API-wide block (needed for
    // image search and rich results).
    "Allow: /prompt_share/api/media/",
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
