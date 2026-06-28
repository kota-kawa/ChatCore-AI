import { useEffect, useRef } from "react";

import { formatMemoOutput } from "../../scripts/chat/chat_ui";
import { renderSanitizedHTML } from "../../scripts/chat/message_utils";

// ---------------------------------------------------------------------------
// MemoMarkdown component (renders LLM-formatted markdown)
// ---------------------------------------------------------------------------

// マークダウン形式のテキストをHTMLとしてレンダリングするコンポーネント
// Component to render markdown formatted text as HTML
export function MemoMarkdown({ text, className }: { text: string; className?: string }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  // Markdownのテキストが変更されたときにサニタイズして描画する副作用
  // Effect to render sanitized HTML when markdown text changes
  useEffect(() => {
    if (!containerRef.current) return;
    renderSanitizedHTML(containerRef.current, formatMemoOutput(text || ""));
  }, [text]);
  return <div ref={containerRef} className={className}></div>;
}
