export const SITE_NAME = "Chat Core";

export const DEFAULT_SEO_TITLE = "ChatCore-AI | AIチャット・プロンプト共有・メモ管理";

export const DEFAULT_SEO_DESCRIPTION =
  "ChatCore-AIは、AIチャット、プロンプト共有、メモ保存をひとつにまとめた日本語対応のAIワークスペースです。日々の調査、文章作成、アイデア整理を効率化できます。";

export const DEFAULT_OG_IMAGE_PATH = "/static/Chat-Core-OG-compressed.jpg";
export const DEFAULT_OG_IMAGE_WIDTH = 2048;
export const DEFAULT_OG_IMAGE_HEIGHT = 1070;

export const TWITTER_SITE = process.env.NEXT_PUBLIC_TWITTER_SITE || "";

const ABSOLUTE_URL_PATTERN = /^https?:\/\//i;

/**
 * サイトの公開URLを取得する
 * Get the public URL of the site
 */
export function getPublicSiteUrl() {
  const rawUrl = process.env.NEXT_PUBLIC_SITE_URL || "";

  if (!rawUrl) return "";

  // プロトコルが付与されていない場合はhttpsを付与する
  // Prepend https if the protocol is missing
  const withProtocol = ABSOLUTE_URL_PATTERN.test(rawUrl) ? rawUrl : `https://${rawUrl}`;
  // 末尾のパスセパレーターを削除する
  // Remove trailing slashes
  return withProtocol.replace(/\/+$/, "");
}

/**
 * 与えられたパスを絶対URLに変換する
 * Convert the given path to an absolute URL
 */
export function absoluteUrl(pathOrUrl: string, baseUrl = getPublicSiteUrl()) {
  if (!pathOrUrl) return "";
  // すでに絶対URLの場合はそのまま返す
  // Return as is if already an absolute URL
  if (ABSOLUTE_URL_PATTERN.test(pathOrUrl)) return pathOrUrl;
  if (!baseUrl) return pathOrUrl;
  
  // パスがスラッシュで始まらない場合はスラッシュを付与する
  // Prepend a slash if the path does not start with one
  const normalizedPath = pathOrUrl.startsWith("/") ? pathOrUrl : `/${pathOrUrl}`;
  return `${baseUrl}${normalizedPath}`;
}

/**
 * SEOのdescription用にMarkdown構文を削除する
 * Strip Markdown syntax for SEO descriptions
 */
export function stripMarkdownForDescription(value: string) {
  return value
    .replace(/```[\s\S]*?```/g, " ") // コードブロックの削除 / Remove code blocks
    .replace(/`([^`]+)`/g, "$1") // インラインコードの削除 / Remove inline code
    .replace(/!\[[^\]]*]\([^)]*\)/g, " ") // 画像リンクの削除 / Remove image links
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1") // リンクのテキストのみ抽出 / Extract text from links
    .replace(/[#>*_\-]/g, " ") // 見出しやリストなどの記号を削除 / Remove formatting symbols
    .replace(/\s+/g, " ") // 余分な空白をまとめる / Collapse whitespaces
    .trim();
}

/**
 * SEO用にテキストを一定文字数で切り詰める
 * Truncate text for SEO purposes to a certain length
 */
export function truncateSeoText(value: string, maxLength = 140) {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (normalized.length <= maxLength) return normalized;
  // 最大文字数を超えた場合は省略記号を付与する
  // Add an ellipsis if it exceeds the maximum length
  return `${normalized.slice(0, maxLength - 1).trimEnd()}...`;
}

/**
 * JSON-LD用スクリプトのコンテンツをエスケープして生成する
 * Generate and escape script content for JSON-LD
 */
export function jsonLdScriptContent(data: Record<string, unknown> | Record<string, unknown>[]) {
  return JSON.stringify(data).replace(/</g, "\\u003c");
}
