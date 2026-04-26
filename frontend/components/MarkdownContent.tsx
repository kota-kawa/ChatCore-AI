import DOMPurify from "dompurify";
import { marked } from "marked";
import { useMemo } from "react";
import { sanitizeClassAttributeValue } from "../scripts/core/html";

const ALLOWED_TAGS = new Set([
  "p", "br", "strong", "em", "code", "pre", "ul", "ol", "li",
  "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "hr",
  "table", "thead", "tbody", "tr", "th", "td", "a", "img",
]);
const ALLOWED_ATTRS = new Set(["href", "src", "alt", "title", "class", "target"]);
const SAFE_URI_PATTERN = /^(?:(?:https?|mailto|tel):|\/(?!\/)|#|\.{1,2}\/|[^:/?#]+(?:[/?#]|$))/i;
const MARKDOWN_HTML_CACHE_LIMIT = 120;
const markdownHtmlCache = new Map<string, string>();

function rememberMarkdownHtml(key: string, value: string) {
  markdownHtmlCache.set(key, value);
  if (markdownHtmlCache.size <= MARKDOWN_HTML_CACHE_LIMIT) return;
  const oldestKey = markdownHtmlCache.keys().next().value;
  if (oldestKey) {
    markdownHtmlCache.delete(oldestKey);
  }
}

function normalizeSanitizedHtml(html: string): string {
  if (typeof document === "undefined") return "";

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

  Array.from(template.content.querySelectorAll("a")).forEach((node) => {
    node.setAttribute("target", "_blank");
    node.setAttribute("rel", "noopener noreferrer");
  });

  return template.innerHTML;
}

function renderMarkdownToSafeHtml(text: string): string {
  if (!text || typeof window === "undefined") return "";

  const cached = markdownHtmlCache.get(text);
  if (cached !== undefined) return cached;

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

export default function MarkdownContent({ text, className }: Props) {
  const html = useMemo(() => {
    return renderMarkdownToSafeHtml(text);
  }, [text]);

  return <div className={className} dangerouslySetInnerHTML={{ __html: html }} />;
}
