import { marked } from "marked";
import { sanitizeClassAttributeValue } from "./html";

// MarkdownをXSS安全なHTMLへ変換する共通パイプライン。
// ブラウザ（DOMPurify + document）とサーバー（jsdom版DOMPurify + jsdom document）の
// 双方から同一のサニタイズ規則で利用できるよう、環境依存物は引数で注入する。
// Shared pipeline that converts Markdown into XSS-safe HTML.
// Environment-specific objects are injected so the exact same sanitization rules
// run in the browser (DOMPurify + document) and on the server (jsdom-backed DOMPurify + jsdom document).

// サニタイズ後に許可するHTMLタグのセット
// Set of HTML tags allowed after sanitization
const ALLOWED_TAGS = [
  "p", "br", "strong", "em", "code", "pre", "ul", "ol", "li",
  "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "hr",
  "table", "thead", "tbody", "tr", "th", "td", "a", "img", "input",
];
// 許可するHTML属性のセット
// Set of HTML attributes allowed after sanitization
const ALLOWED_ATTRS = ["href", "src", "alt", "title", "class", "target", "type", "checked", "disabled"];
// 許可するURIスキームの正規表現パターン（XSS対策）
// Regex pattern for allowed URI schemes (XSS prevention)
const SAFE_URI_PATTERN = /^(?:(?:https?|mailto|tel):|\/(?!\/)|#|\.{1,2}\/|[^:/?#]+(?:[/?#]|$))/i;
// レンダリング済みHTMLのキャッシュ上限
// Maximum number of entries in the rendered HTML cache
const MARKDOWN_HTML_CACHE_LIMIT = 120;

// DOMPurify互換のサニタイザーが満たすべき最小インターフェース
// Minimal interface a DOMPurify-compatible sanitizer must satisfy
export type MarkdownSanitizer = {
  sanitize(source: string, config: Record<string, unknown>): string;
};

// サニタイズ済みHTMLを正規化する（クラス名・リンク・inputを安全な状態にする）
// Normalize sanitized HTML (make class names, links, and inputs safe)
function normalizeSanitizedHtml(html: string, doc: Document): string {
  const template = doc.createElement("template");
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

// 注入されたサニタイザーとdocumentでMarkdownレンダラーを生成する（LRUキャッシュ付き）
// Create a Markdown renderer bound to the injected sanitizer and document (with an LRU cache)
export function createMarkdownHtmlRenderer(purify: MarkdownSanitizer, doc: Document) {
  const cache = new Map<string, string>();

  // 変換済みHTMLをキャッシュに保存し、上限超過時は最古エントリを削除する
  // Save converted HTML to cache; evict the oldest entry when over the limit
  const remember = (key: string, value: string) => {
    cache.set(key, value);
    if (cache.size <= MARKDOWN_HTML_CACHE_LIMIT) return;
    const oldestKey = cache.keys().next().value;
    if (oldestKey) {
      cache.delete(oldestKey);
    }
  };

  return function renderMarkdownToSafeHtml(text: string): string {
    if (!text) return "";

    // キャッシュヒット時はそのまま返す
    // Return cached result if available
    const cached = cache.get(text);
    if (cached !== undefined) return cached;

    // MarkedでMarkdownをHTMLに変換し、DOMPurifyでサニタイズする
    // Convert Markdown to HTML with Marked, then sanitize with DOMPurify
    const raw = marked.parse(text, { async: false, gfm: true, breaks: true });
    const rawStr = typeof raw === "string" ? raw : "";
    let clean = purify.sanitize(rawStr, {
      ALLOWED_TAGS,
      ALLOWED_ATTR: ALLOWED_ATTRS,
      ALLOWED_URI_REGEXP: SAFE_URI_PATTERN,
      ALLOW_DATA_ATTR: false
    });
    clean = normalizeSanitizedHtml(clean, doc);
    remember(text, clean);
    return clean;
  };
}
