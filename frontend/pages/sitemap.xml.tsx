import type { GetServerSideProps } from "next";

function normalizeHostHeader(header: string | string[] | undefined) {
  if (Array.isArray(header)) return header[0] || "";
  return header || "";
}

function normalizeProtoHeader(header: string | string[] | undefined) {
  const raw = Array.isArray(header) ? header[0] : header;
  if (!raw) return "";
  return raw.split(",")[0]?.trim() || "";
}

function xmlEscape(value: string) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

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

export const getServerSideProps: GetServerSideProps = async (context) => {
  const origin = resolveOrigin(context);
  const lastmod = new Date().toISOString();
  const publicRoutes = [
    { path: "/", changefreq: "daily", priority: "1.0" },
    { path: "/prompt_share", changefreq: "daily", priority: "0.9" }
  ];

  const urls = publicRoutes
    .map(({ path, changefreq, priority }) => {
      const loc = origin ? `${origin}${path}` : path;
      return [
        "  <url>",
        `    <loc>${xmlEscape(loc)}</loc>`,
        `    <lastmod>${lastmod}</lastmod>`,
        `    <changefreq>${changefreq}</changefreq>`,
        `    <priority>${priority}</priority>`,
        "  </url>"
      ].join("\n");
    })
    .join("\n");

  const body = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    urls,
    "</urlset>",
    ""
  ].join("\n");

  context.res.setHeader("Content-Type", "application/xml; charset=utf-8");
  context.res.setHeader("Cache-Control", "public, max-age=3600, s-maxage=3600");
  context.res.write(body);
  context.res.end();

  return { props: {} };
};

export default function SitemapXml() {
  return null;
}
