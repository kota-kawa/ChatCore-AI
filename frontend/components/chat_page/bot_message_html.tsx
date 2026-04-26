import { memo, useEffect, useLayoutEffect, useMemo, useRef } from "react";

import { formatLLMOutput } from "../../scripts/chat/chat_ui";
import { renderSanitizedHTML } from "../../scripts/chat/message_utils";

const useIsomorphicLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;

type BotMessageHtmlProps = {
  text: string;
};

function BotMessageHtmlComponent({ text }: BotMessageHtmlProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const formatted = useMemo(() => formatLLMOutput(text), [text]);

  useIsomorphicLayoutEffect(() => {
    if (!containerRef.current) return;
    renderSanitizedHTML(containerRef.current, formatted);
  }, [formatted]);

  return <div ref={containerRef}></div>;
}

export const BotMessageHtml = memo(BotMessageHtmlComponent);
BotMessageHtml.displayName = "BotMessageHtml";
