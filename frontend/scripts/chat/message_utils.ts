// message_utils.ts – 共通メッセージユーティリティ
// Provides shared chat message helpers.
// --------------------------------------------------
import DOMPurify from "dompurify";
import { escapeHtml, sanitizeClassAttributeValue } from "../core/html";
import { patchElementChildren } from "../../lib/chat_page/streaming_dom_patch";

// 回答 HTML の余分な空行・空段落・連続した <br> を詰める。
function compactBotMessageHtml(html: string) {
  return html
    .replace(/[\u200B-\u200D\u2060\uFEFF]/g, "")
    .replace(/(?:<br\s*\/?>\s*){3,}/gi, "<br><br>")
    .replace(/<p>(?:\s|&nbsp;|&#160;|&#xA0;|&#8203;|&#x200b;|<br\s*\/?>)*<\/p>/gi, "")
    .replace(/(<\/(?:p|ul|ol|pre|blockquote|table|h[1-6])>\s*)(?:<br\s*\/?>\s*)+/gi, "$1")
    .replace(/(?:<br\s*\/?>\s*)+(<(?:p|ul|ol|pre|blockquote|table|h[1-6]|hr)\b)/gi, "$1")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

const SAFE_URI_PATTERN = /^(?:(?:https?|mailto|tel):|\/(?!\/)|#|\.{1,2}\/|[^:/?#]+(?:[/?#]|$))/i;
const SANITIZED_HTML_CACHE_LIMIT = 160;
const DEFAULT_ALLOWED_MESSAGE_TAGS = [
  "a",
  "strong",
  "em",
  "code",
  "pre",
  "br",
  "p",
  "ul",
  "ol",
  "li",
  "blockquote",
  "img",
  "input",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "hr",
  "table",
  "thead",
  "tbody",
  "tr",
  "th",
  "td",
  "div",
  "span",
  "button",
  "i",
  "details",
  "summary"
];
const sanitizedHtmlCache = new Map<string, string>();

type SanitizeMessageHtmlOptions = {
  allowedTags?: string[];
  compactBotMessage?: boolean;
};

function rememberSanitizedHtml(key: string, value: string) {
  sanitizedHtmlCache.set(key, value);
  if (sanitizedHtmlCache.size <= SANITIZED_HTML_CACHE_LIMIT) return;
  const oldestKey = sanitizedHtmlCache.keys().next().value;
  if (oldestKey) {
    sanitizedHtmlCache.delete(oldestKey);
  }
}

function normalizeSanitizedHtml(html: string) {
  if (typeof document === "undefined") return html;

  const template = document.createElement("template");
  template.innerHTML = html;

  Array.from(template.content.querySelectorAll("[class]")).forEach((node) => {
    const safeClassNames = sanitizeClassAttributeValue(node.getAttribute("class"));
    if (safeClassNames) {
      node.setAttribute("class", safeClassNames);
      return;
    }
    node.removeAttribute("class");
  });

  Array.from(template.content.querySelectorAll("a[target='_blank']")).forEach((node) => {
    node.setAttribute("rel", "noopener noreferrer");
  });

  Array.from(template.content.querySelectorAll("input")).forEach((node) => {
    if (node.getAttribute("type") !== "checkbox") {
      node.remove();
      return;
    }
    node.setAttribute("disabled", "");
  });

  return template.innerHTML;
}

function sanitizeMessageHtml(dirtyHtml: string, options: SanitizeMessageHtmlOptions = {}) {
  const allowedTags = options.allowedTags || DEFAULT_ALLOWED_MESSAGE_TAGS;
  const cacheKey = `${options.compactBotMessage ? "bot" : "plain"}\0${allowedTags.join(",")}\0${dirtyHtml}`;
  const cached = sanitizedHtmlCache.get(cacheKey);
  if (cached !== undefined) return cached;

  const purifier = DOMPurify as typeof DOMPurify & {
    sanitize?: (dirty: string, config?: Record<string, unknown>) => string;
  };
  let clean =
    typeof purifier.sanitize === "function"
      ? purifier.sanitize(dirtyHtml, {
          ALLOWED_TAGS: allowedTags,
          ALLOWED_ATTR: ["href", "src", "alt", "title", "target", "class", "type", "checked", "disabled", "referrerpolicy"],
          ALLOWED_URI_REGEXP: SAFE_URI_PATTERN,
          ALLOW_DATA_ATTR: false
        })
      : escapeHtml(dirtyHtml);

  clean = normalizeSanitizedHtml(clean);
  if (options.compactBotMessage) {
    clean = compactBotMessageHtml(clean);
  }

  rememberSanitizedHtml(cacheKey, clean);
  return clean;
}

/**
 * HTML をサニタイズして挿入する
 * @param element   挿入先
 * @param dirtyHtml サニタイズ前 HTML
 * @param allowed   許可タグ（省略時はデフォルト）
 */
function renderSanitizedHTML(
  element: HTMLElement,
  dirtyHtml: string,
  allowed: string[] = DEFAULT_ALLOWED_MESSAGE_TAGS
) {
  const isBotMessage = element.classList.contains("bot-message");
  element.innerHTML = sanitizeMessageHtml(dirtyHtml, {
    allowedTags: allowed,
    compactBotMessage: isBotMessage
  });
}

/**
 * サニタイズ済み HTML を差分適用する（生成中の再描画向け）
 * innerHTML の丸ごと差し替えと違い、既存ノードを使い回すため
 * favicon の再読み込みによる点滅や、クリック中のノード消失が起きない。
 * @param element   挿入先
 * @param dirtyHtml サニタイズ前 HTML
 * @param allowed   許可タグ（省略時はデフォルト）
 */
function patchSanitizedHTML(
  element: HTMLElement,
  dirtyHtml: string,
  allowed: string[] = DEFAULT_ALLOWED_MESSAGE_TAGS
) {
  const isBotMessage = element.classList.contains("bot-message");
  patchElementChildren(
    element,
    sanitizeMessageHtml(dirtyHtml, {
      allowedTags: allowed,
      compactBotMessage: isBotMessage
    })
  );
}

export { sanitizeMessageHtml, renderSanitizedHTML, patchSanitizedHTML };
