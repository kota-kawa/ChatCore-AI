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

export const getServerSideProps: GetServerSideProps = async (context) => {
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

  const body = [
    "User-agent: *",
    "Allow: /",
    "Disallow: /api/",
    "Disallow: /admin",
    "Disallow: /login",
    "Disallow: /register",
    "Disallow: /settings",
    "Disallow: /memo",
    "Disallow: /prompt_share/manage_prompts",
    "Disallow: /google-login",
    "Disallow: /google-callback",
    "Disallow: /logout",
    "",
    `Sitemap: ${origin ? `${origin}/sitemap.xml` : "/sitemap.xml"}`,
    ""
  ].join("\n");

  context.res.setHeader("Content-Type", "text/plain; charset=utf-8");
  context.res.setHeader("Cache-Control", "public, max-age=3600, s-maxage=3600");
  context.res.write(body);
  context.res.end();

  return { props: {} };
};

export default function RobotsTxt() {
  return null;
}
