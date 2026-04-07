import { useEffect, useMemo, useRef } from "react";

import { formatUserInputForDisplay } from "../../scripts/chat/chat_ui";
import { renderSanitizedHTML } from "../../scripts/chat/message_utils";

type UserMessageHtmlProps = {
  text: string;
};

export function UserMessageHtml({ text }: UserMessageHtmlProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const formatted = useMemo(() => formatUserInputForDisplay(text), [text]);

  useEffect(() => {
    if (!containerRef.current) return;
    renderSanitizedHTML(containerRef.current, formatted);
  }, [formatted]);

  return <div ref={containerRef}></div>;
}
