import { memo, useEffect, useLayoutEffect, useMemo, useRef } from "react";

import { formatLLMOutput } from "../../scripts/chat/chat_ui";
import { renderSanitizedHTML } from "../../scripts/chat/message_utils";

const useIsomorphicLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;
const WEB_SEARCH_SOURCES_ANIMATION_MS = 240;
const WEB_SEARCH_SOURCES_ANIMATION_EASING = "cubic-bezier(0.22, 1, 0.36, 1)";
const activeWebSearchSourceAnimations = new WeakMap<HTMLDetailsElement, Animation>();
const WEB_SEARCH_SOURCES_REVEAL_PADDING = 16;

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

function setWebSearchOverflowState(sourceDetails: HTMLElement) {
  const row = sourceDetails.closest<HTMLElement>(".chat-message-row");
  const wrapper = sourceDetails.closest<HTMLElement>(".message-wrapper");
  const selector = "details.web-search-sources__step-details[open], details.web-search-sources__source-details[open]";
  const hasOpenSourceDetails = Boolean(row?.querySelector(selector));

  [row, wrapper].forEach((element) => {
    if (!element) return;
    if (hasOpenSourceDetails) {
      element.dataset.webSearchOverflowActive = "true";
      return;
    }
    delete element.dataset.webSearchOverflowActive;
  });
}

function cancelWebSearchSourcesAnimation(details: HTMLDetailsElement) {
  const activeAnimation = activeWebSearchSourceAnimations.get(details);
  if (!activeAnimation) return;
  activeAnimation.onfinish = null;
  activeAnimation.oncancel = null;
  activeAnimation.cancel();
  activeWebSearchSourceAnimations.delete(details);
}

function getChatMessagesScroller(element: HTMLElement) {
  return element.closest<HTMLElement>(".chat-messages");
}

function revealWebSearchSources(details: HTMLDetailsElement) {
  const scroller = getChatMessagesScroller(details);
  if (!scroller) {
    details.scrollIntoView({ block: "nearest" });
    return;
  }

  const scrollerRect = scroller.getBoundingClientRect();
  const detailsRect = details.getBoundingClientRect();
  const availableHeight = scrollerRect.height - WEB_SEARCH_SOURCES_REVEAL_PADDING * 2;

  if (detailsRect.height <= availableHeight) {
    if (detailsRect.top < scrollerRect.top + WEB_SEARCH_SOURCES_REVEAL_PADDING) {
      scroller.scrollTop -= scrollerRect.top + WEB_SEARCH_SOURCES_REVEAL_PADDING - detailsRect.top;
      return;
    }

    if (detailsRect.bottom > scrollerRect.bottom - WEB_SEARCH_SOURCES_REVEAL_PADDING) {
      scroller.scrollTop += detailsRect.bottom - (scrollerRect.bottom - WEB_SEARCH_SOURCES_REVEAL_PADDING);
    }
    return;
  }

  if (
    detailsRect.top < scrollerRect.top + WEB_SEARCH_SOURCES_REVEAL_PADDING ||
    detailsRect.bottom > scrollerRect.bottom - WEB_SEARCH_SOURCES_REVEAL_PADDING
  ) {
    scroller.scrollTop += detailsRect.top - (scrollerRect.top + WEB_SEARCH_SOURCES_REVEAL_PADDING);
  }
}

function scheduleWebSearchSourcesReveal(details: HTMLDetailsElement) {
  if (typeof window === "undefined") return;

  window.requestAnimationFrame(() => {
    revealWebSearchSources(details);
    window.requestAnimationFrame(() => {
      revealWebSearchSources(details);
    });
  });

  [WEB_SEARCH_SOURCES_ANIMATION_MS + 40, WEB_SEARCH_SOURCES_ANIMATION_MS + 180].forEach((delay) => {
    window.setTimeout(() => {
      revealWebSearchSources(details);
    }, delay);
  });
}

function animateWebSearchSources(details: HTMLDetailsElement, shouldOpen: boolean) {
  const list = getWebSearchSourcesList(details);
  if (!list || typeof list.animate !== "function" || prefersReducedMotion()) {
    cancelWebSearchSourcesAnimation(details);
    details.open = shouldOpen;
    delete details.dataset.webSearchSourcesState;
    if (list) resetWebSearchSourcesListStyles(list);
    if (shouldOpen) scheduleWebSearchSourcesReveal(details);
    return;
  }

  const currentHeight = list.getBoundingClientRect().height;
  cancelWebSearchSourcesAnimation(details);

  let startHeight = currentHeight;
  let endHeight = 0;

  if (shouldOpen) {
    details.open = true;
    list.style.height = "auto";
    endHeight = list.scrollHeight;
    startHeight = currentHeight > 0 ? currentHeight : 0;
    scheduleWebSearchSourcesReveal(details);
  } else {
    startHeight = currentHeight || list.scrollHeight;
  }

  details.dataset.webSearchSourcesState = shouldOpen ? "opening" : "closing";
  list.style.overflow = "hidden";
  list.style.height = `${startHeight}px`;
  list.style.opacity = shouldOpen ? (startHeight > 0 ? "1" : "0") : "1";
  list.style.transform = shouldOpen && startHeight === 0 ? "translateY(-6px)" : "translateY(0)";
  void list.offsetHeight;

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
    if (shouldOpen) scheduleWebSearchSourcesReveal(details);
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

  container
    .querySelectorAll<HTMLDetailsElement>(
      "details.web-search-sources__step-details, details.web-search-sources__source-details"
    )
    .forEach((details) => {
      const handleToggle = () => {
        setWebSearchOverflowState(details);
        if (details.open) scheduleWebSearchSourcesReveal(details);
      };

      details.addEventListener("toggle", handleToggle);
      setWebSearchOverflowState(details);
      cleanupCallbacks.push(() => {
        details.removeEventListener("toggle", handleToggle);
        const row = details.closest<HTMLElement>(".chat-message-row");
        const wrapper = details.closest<HTMLElement>(".message-wrapper");
        if (row) delete row.dataset.webSearchOverflowActive;
        if (wrapper) delete wrapper.dataset.webSearchOverflowActive;
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
