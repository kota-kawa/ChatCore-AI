import { memo, useEffect, useLayoutEffect, useMemo, useRef } from "react";

import { formatLLMOutput } from "../../scripts/chat/chat_ui";
import { renderSanitizedHTML } from "../../scripts/chat/message_utils";

const useIsomorphicLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;
const WEB_SEARCH_SOURCES_ANIMATION_MS = 240;
const WEB_SEARCH_SOURCES_ANIMATION_EASING = "cubic-bezier(0.22, 1, 0.36, 1)";
const activeWebSearchSourceAnimations = new WeakMap<HTMLDetailsElement, Animation>();

type BotMessageHtmlProps = {
  text: string;
};

function prefersReducedMotion() {
  return typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function getWebSearchSourcesList(details: HTMLDetailsElement) {
  return details.querySelector<HTMLElement>(".web-search-sources__list");
}

function resetWebSearchSourcesListStyles(list: HTMLElement) {
  list.style.height = "";
  list.style.overflow = "";
  list.style.opacity = "";
  list.style.transform = "";
}

function cancelWebSearchSourcesAnimation(details: HTMLDetailsElement) {
  const activeAnimation = activeWebSearchSourceAnimations.get(details);
  if (!activeAnimation) return;
  activeAnimation.onfinish = null;
  activeAnimation.oncancel = null;
  activeAnimation.cancel();
  activeWebSearchSourceAnimations.delete(details);
}

function animateWebSearchSources(details: HTMLDetailsElement, shouldOpen: boolean) {
  const list = getWebSearchSourcesList(details);
  if (!list || typeof list.animate !== "function" || prefersReducedMotion()) {
    cancelWebSearchSourcesAnimation(details);
    details.open = shouldOpen;
    delete details.dataset.webSearchSourcesState;
    if (list) resetWebSearchSourcesListStyles(list);
    return;
  }

  const currentHeight = list.getBoundingClientRect().height;
  cancelWebSearchSourcesAnimation(details);

  if (shouldOpen) {
    details.open = true;
  }

  const startHeight = shouldOpen ? currentHeight : currentHeight || list.scrollHeight;
  const endHeight = shouldOpen ? list.scrollHeight : 0;

  details.dataset.webSearchSourcesState = shouldOpen ? "opening" : "closing";
  list.style.overflow = "hidden";
  list.style.height = `${startHeight}px`;
  list.style.opacity = shouldOpen ? (startHeight > 0 ? "1" : "0") : "1";
  list.style.transform = shouldOpen && startHeight === 0 ? "translateY(-6px)" : "translateY(0)";

  const animation = list.animate(
    [
      {
        height: `${startHeight}px`,
        opacity: shouldOpen || startHeight > 0 ? 1 : 0,
        transform: shouldOpen && startHeight === 0 ? "translateY(-6px)" : "translateY(0)"
      },
      {
        height: `${endHeight}px`,
        opacity: shouldOpen ? 1 : 0,
        transform: shouldOpen ? "translateY(0)" : "translateY(-6px)"
      }
    ],
    {
      duration: WEB_SEARCH_SOURCES_ANIMATION_MS,
      easing: WEB_SEARCH_SOURCES_ANIMATION_EASING,
      fill: "forwards"
    }
  );

  activeWebSearchSourceAnimations.set(details, animation);
  animation.onfinish = () => {
    if (activeWebSearchSourceAnimations.get(details) !== animation) return;
    activeWebSearchSourceAnimations.delete(details);
    details.open = shouldOpen;
    delete details.dataset.webSearchSourcesState;
    resetWebSearchSourcesListStyles(list);
  };
}

function bindWebSearchSourcesAccordions(container: HTMLElement) {
  const cleanupCallbacks: Array<() => void> = [];

  container.querySelectorAll<HTMLDetailsElement>("details.web-search-sources").forEach((details) => {
    const summary = details.querySelector<HTMLElement>(".web-search-sources__summary");
    if (!summary) return;

    const handleSummaryClick = (event: MouseEvent) => {
      event.preventDefault();
      const shouldOpen = !details.open || details.dataset.webSearchSourcesState === "closing";
      animateWebSearchSources(details, shouldOpen);
    };

    summary.addEventListener("click", handleSummaryClick);
    cleanupCallbacks.push(() => {
      summary.removeEventListener("click", handleSummaryClick);
      cancelWebSearchSourcesAnimation(details);
      const list = getWebSearchSourcesList(details);
      if (list) resetWebSearchSourcesListStyles(list);
    });
  });

  return () => {
    cleanupCallbacks.forEach((cleanup) => {
      cleanup();
    });
  };
}

function BotMessageHtmlComponent({ text }: BotMessageHtmlProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const formatted = useMemo(() => formatLLMOutput(text), [text]);

  useIsomorphicLayoutEffect(() => {
    if (!containerRef.current) return;
    renderSanitizedHTML(containerRef.current, formatted);
    return bindWebSearchSourcesAccordions(containerRef.current);
  }, [formatted]);

  return <div ref={containerRef}></div>;
}

export const BotMessageHtml = memo(BotMessageHtmlComponent);
BotMessageHtml.displayName = "BotMessageHtml";
