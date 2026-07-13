import DOMPurify from "dompurify";
import { useEffect, useMemo, useState } from "react";
import { createMarkdownHtmlRenderer } from "../scripts/core/markdown_safe_html";

// ブラウザ環境用のMarkdownレンダラー（初回利用時に生成して使い回す）
// Markdown renderer for the browser environment (created lazily and reused)
let clientRenderer: ((text: string) => string) | null = null;

// MarkdownテキストをXSS安全なHTMLに変換する（ブラウザ専用・キャッシュ付き）
// Convert Markdown text to XSS-safe HTML (browser only, with caching)
function renderMarkdownToSafeHtml(text: string): string {
  if (!text || typeof window === "undefined" || typeof document === "undefined") return "";
  if (!clientRenderer) {
    clientRenderer = createMarkdownHtmlRenderer(DOMPurify, document);
  }
  return clientRenderer(text);
}

type Props = {
  text: string;
  className?: string;
  // SSRで事前サニタイズ済みのHTML。指定時はそれをそのまま描画する（クローラにも本文が見える）。
  // Pre-sanitized HTML rendered on the server. When provided it is rendered as-is (visible to crawlers too).
  ssrHtml?: string;
};

// MarkdownテキストをレンダリングするReactコンポーネント
// React component that renders Markdown text as safe HTML
export default function MarkdownContent({ text, className, ssrHtml }: Props) {
  // Markdown変換とサニタイズは DOM (marked→DOMPurify→document) に依存するためブラウザ側でのみ実行できる。
  // ssrHtml 指定時はサーバー・クライアントとも同じHTMLを描画するためハイドレーション不一致は起きない。
  // 未指定時は SSR とハイドレーション初回を空にしてサーバー出力と一致させ、マウント後に本文を挿入する。
  // dangerouslySetInnerHTML はハイドレーション時に innerHTML を再調整しないため、
  // マウント後の再レンダリングを行わないと本文が空のまま表示されてしまう。
  // Markdown parsing and sanitization depend on the DOM (marked→DOMPurify→document), so they only run in the browser.
  // When ssrHtml is provided, both server and client render the same HTML, so no hydration mismatch occurs.
  // Otherwise render empty on the server and on the initial hydration render, then inject the content after mount.
  // React does not reconcile dangerouslySetInnerHTML during hydration, so without a post-mount re-render the body stays empty.
  const [isMounted, setIsMounted] = useState(false);
  useEffect(() => {
    setIsMounted(true);
  }, []);

  // ssrHtml・テキスト・マウント状態が変わった場合のみHTMLを再計算する
  // Recompute HTML only when ssrHtml, text, or mount state changes
  const html = useMemo(() => {
    if (typeof ssrHtml === "string") return ssrHtml;
    if (!isMounted) return "";
    return renderMarkdownToSafeHtml(text);
  }, [ssrHtml, text, isMounted]);

  return <div className={className} dangerouslySetInnerHTML={{ __html: html }} />;
}
