import { marked } from "marked";
import { useMemo } from "react";

const ALLOWED_TAGS = new Set([
  "p", "br", "strong", "em", "code", "pre", "ul", "ol", "li",
  "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "hr",
  "table", "thead", "tbody", "tr", "th", "td", "a", "img",
]);
const ALLOWED_ATTRS = new Set(["href", "src", "alt", "title", "class", "target"]);

function sanitizeNode(node: Node): Node | null {
  if (node.nodeType === Node.TEXT_NODE) {
    return document.createTextNode(node.textContent || "");
  }
  if (node.nodeType !== Node.ELEMENT_NODE) return null;

  const el = node as HTMLElement;
  const tag = el.tagName.toLowerCase();

  if (!ALLOWED_TAGS.has(tag)) {
    const frag = document.createDocumentFragment();
    el.childNodes.forEach((child) => {
      const cleaned = sanitizeNode(child);
      if (cleaned) frag.appendChild(cleaned);
    });
    return frag;
  }

  const clean = document.createElement(tag);
  el.getAttributeNames().forEach((name) => {
    if (!ALLOWED_ATTRS.has(name)) return;
    const value = el.getAttribute(name) || "";
    if ((name === "href" || name === "src") && /^javascript:/i.test(value.trim())) return;
    clean.setAttribute(name, value);
  });
  if (tag === "a") {
    clean.setAttribute("target", "_blank");
    clean.setAttribute("rel", "noopener noreferrer");
  }
  el.childNodes.forEach((child) => {
    const cleaned = sanitizeNode(child);
    if (cleaned) clean.appendChild(cleaned);
  });
  return clean;
}

function sanitize(html: string): string {
  if (typeof document === "undefined") return "";
  const tpl = document.createElement("template");
  tpl.innerHTML = html;
  const div = document.createElement("div");
  tpl.content.childNodes.forEach((node) => {
    const cleaned = sanitizeNode(node);
    if (cleaned) div.appendChild(cleaned);
  });
  return div.innerHTML;
}

type Props = {
  text: string;
  className?: string;
};

export default function MarkdownContent({ text, className }: Props) {
  const html = useMemo(() => {
    if (!text) return "";
    const raw = marked.parse(text, { async: false, gfm: true, breaks: true });
    const rawStr = typeof raw === "string" ? raw : "";
    return sanitize(rawStr);
  }, [text]);

  return <div className={className} dangerouslySetInnerHTML={{ __html: html }} />;
}
