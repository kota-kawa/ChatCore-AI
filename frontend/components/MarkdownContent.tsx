import DOMPurify from "dompurify";
import { marked } from "marked";
import { useMemo } from "react";
import { sanitizeClassAttributeValue } from "../scripts/core/html";

// サニタイズ後に許可するHTMLタグのセット
// Set of HTML tags allowed after sanitization
const ALLOWED_TAGS = new Set([
  "p", "br", "strong", "em", "code", "pre", "ul", "ol", "li",
  "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "hr",
  "table", "thead", "tbody", "tr", "th", "td", "a", "img", "input",
]);
// 許可するHTML属性のセット
// Set of HTML attributes allowed after sanitization
const ALLOWED_ATTRS = new Set(["href", "src", "alt", "title", "class", "target", "type", "checked", "disabled"]);
// 許可するURIスキームの正規表現パターン（XSS対策）
// Regex pattern for allowed URI schemes (XSS prevention)
const SAFE_URI_PATTERN = /^(?:(?:https?|mailto|tel):|\/(?!\/)|#|\.{1,2}\/|[^:/?#]+(?:[/?#]|$))/i;
// レンダリング済みHTMLのキャッシュ上限
// Maximum number of entries in the rendered HTML cache
const MARKDOWN_HTML_CACHE_LIMIT = 120;
// Markdownから変換したHTMLのLRUキャッシュ
// LRU cache for HTML converted from Markdown
const markdownHtmlCache = new Map<string, string>();

// 変換済みHTMLをキャッシュに保存し、上限超過時は最古エントリを削除する
// Save converted HTML to cache; evict the oldest entry when over the limit
function rememberMarkdownHtml(key: string, value: string) {
  markdownHtmlCache.set(key, value);
  if (markdownHtmlCache.size <= MARKDOWN_HTML_CACHE_LIMIT) return;
  const oldestKey = markdownHtmlCache.keys().next().value;
  if (oldestKey) {
    markdownHtmlCache.delete(oldestKey);
  }
}

// サニタイズ済みHTMLを正規化する（クラス名・リンク・inputを安全な状態にする）
// Normalize sanitized HTML (make class names, links, and inputs safe)
function normalizeSanitizedHtml(html: string): string {
  if (typeof document === "undefined") return "";

  const template = document.createElement("template");
  template.innerHTML = html;

  // クラス属性をサニタイズし、安全でないクラス名を除去する
  // Sanitize class attributes and remove unsafe class names
  Array.from(template.content.querySelectorAll("[class]")).forEach((node) => {
    const safeClassNames = sanitizeClassAttributeValue(node.getAttribute("class"));
    if (safeClassNames) {
      node.setAttribute("class", safeClassNames);
      return;
    }
    node.removeAttribute("class");
  });

  // リンクを新しいタブで安全に開くよう設定する
  // Configure links to open safely in a new tab
  Array.from(template.content.querySelectorAll("a")).forEach((node) => {
    node.setAttribute("target", "_blank");
    node.setAttribute("rel", "noopener noreferrer");
  });

  // チェックボックス以外のinput要素を除去し、チェックボックスは無効化する
  // Remove non-checkbox input elements; disable checkboxes
  Array.from(template.content.querySelectorAll("input")).forEach((node) => {
    if (node.getAttribute("type") !== "checkbox") {
      node.remove();
      return;
    }
    node.setAttribute("disabled", "");
  });

  return template.innerHTML;
}

// MarkdownテキストをXSS安全なHTMLに変換する（キャッシュ付き）
// Convert Markdown text to XSS-safe HTML (with caching)
function renderMarkdownToSafeHtml(text: string): string {
  if (!text || typeof window === "undefined") return "";

  // キャッシュヒット時はそのまま返す
  // Return cached result if available
  const cached = markdownHtmlCache.get(text);
  if (cached !== undefined) return cached;

  // MarkedでMarkdownをHTMLに変換し、DOMPurifyでサニタイズする
  // Convert Markdown to HTML with Marked, then sanitize with DOMPurify
  const raw = marked.parse(text, { async: false, gfm: true, breaks: true });
  const rawStr = typeof raw === "string" ? raw : "";
  let clean = DOMPurify.sanitize(rawStr, {
    ALLOWED_TAGS: Array.from(ALLOWED_TAGS),
    ALLOWED_ATTR: Array.from(ALLOWED_ATTRS),
    ALLOWED_URI_REGEXP: SAFE_URI_PATTERN,
    ALLOW_DATA_ATTR: false
  });
  clean = normalizeSanitizedHtml(clean);
  rememberMarkdownHtml(text, clean);
  return clean;
}

type Props = {
  text: string;
  className?: string;
};

// MarkdownテキストをレンダリングするReactコンポーネント
// React component that renders Markdown text as safe HTML
export default function MarkdownContent({ text, className }: Props) {
  // テキストが変わった場合のみHTMLを再計算する
  // Recompute HTML only when text changes
  const html = useMemo(() => {
    return renderMarkdownToSafeHtml(text);
  }, [text]);

  return <div className={className} dangerouslySetInnerHTML={{ __html: html }} />;
}
