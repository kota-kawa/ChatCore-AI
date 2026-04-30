export const SITE_NAME = "Chat Core";

export const DEFAULT_SEO_TITLE = "ChatCore-AI | AIチャット・プロンプト共有・メモ管理";

export const DEFAULT_SEO_DESCRIPTION =
  "ChatCore-AIは、AIチャット、プロンプト共有、メモ保存をひとつにまとめた日本語対応のAIワークスペースです。日々の調査、文章作成、アイデア整理を効率化できます。";

export const DEFAULT_OG_IMAGE_PATH = "/static/img.jpg";

const ABSOLUTE_URL_PATTERN = /^https?:\/\//i;

export function getPublicSiteUrl() {
  const rawUrl = process.env.NEXT_PUBLIC_SITE_URL || "";

  if (!rawUrl) return "";

  const withProtocol = ABSOLUTE_URL_PATTERN.test(rawUrl) ? rawUrl : `https://${rawUrl}`;
  return withProtocol.replace(/\/+$/, "");
}

export function absoluteUrl(pathOrUrl: string, baseUrl = getPublicSiteUrl()) {
  if (!pathOrUrl) return "";
  if (ABSOLUTE_URL_PATTERN.test(pathOrUrl)) return pathOrUrl;
  if (!baseUrl) return pathOrUrl;
  const normalizedPath = pathOrUrl.startsWith("/") ? pathOrUrl : `/${pathOrUrl}`;
  return `${baseUrl}${normalizedPath}`;
}

export function stripMarkdownForDescription(value: string) {
  return value
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/!\[[^\]]*]\([^)]*\)/g, " ")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/[#>*_\-]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function truncateSeoText(value: string, maxLength = 140) {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (normalized.length <= maxLength) return normalized;
  return `${normalized.slice(0, maxLength - 1).trimEnd()}...`;
}

export function jsonLdScriptContent(data: Record<string, unknown> | Record<string, unknown>[]) {
  return JSON.stringify(data).replace(/</g, "\\u003c");
}
