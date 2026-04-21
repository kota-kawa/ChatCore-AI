import { useEffect, useLayoutEffect, useMemo, useRef } from "react";

import { formatUserInputForDisplay } from "../../scripts/chat/chat_ui";
import { renderSanitizedHTML } from "../../scripts/chat/message_utils";

const useIsomorphicLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;

type UserMessageHtmlProps = {
  text: string;
};

export function UserMessageHtml({ text }: UserMessageHtmlProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const formatted = useMemo(() => formatUserInputForDisplay(text), [text]);

  useIsomorphicLayoutEffect(() => {
    if (!containerRef.current) return;
    renderSanitizedHTML(containerRef.current, formatted);
  }, [formatted]);

  return <div ref={containerRef}></div>;
}
