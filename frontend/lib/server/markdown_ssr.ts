import createDOMPurify from "dompurify";
import { JSDOM } from "jsdom";
import { createMarkdownHtmlRenderer } from "../../scripts/core/markdown_safe_html";

// サーバーサイド（getServerSideProps）専用のMarkdown→安全HTMLレンダラー。
// jsdomのwindowでDOMPurifyを初期化し、ブラウザ側と同一のサニタイズ規則で本文をSSRする。
// クライアントバンドルには含めないこと（getServerSideProps内からのみ参照する）。
// Server-side (getServerSideProps only) Markdown → safe-HTML renderer.
// Initializes DOMPurify with a jsdom window so the exact same sanitization rules as the browser run during SSR.
// Must not be pulled into the client bundle (reference it only from getServerSideProps).

// jsdomウィンドウとレンダラーは生成コストが高いため、モジュール内で1度だけ生成して使い回す
// The jsdom window and renderer are expensive to create, so build them once per module and reuse
let serverRenderer: ((text: string) => string) | null = null;

function getServerRenderer() {
  if (!serverRenderer) {
    const { window } = new JSDOM("");
    const purify = createDOMPurify(window);
    serverRenderer = createMarkdownHtmlRenderer(purify, window.document);
  }
  return serverRenderer;
}

// MarkdownテキストをXSS安全なHTMLへ変換する（SSR用）
// Convert Markdown text to XSS-safe HTML (for SSR)
export function renderMarkdownToSafeHtmlOnServer(text: string | null | undefined): string {
  if (!text) return "";
  return getServerRenderer()(text);
}
