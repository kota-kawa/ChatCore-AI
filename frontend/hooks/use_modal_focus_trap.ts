import { useEffect, type RefObject } from "react";

const FOCUSABLE_SELECTOR = [
  "button:not([disabled])",
  "[href]",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

function getFocusableElements(container: HTMLElement) {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter((element) => {
    return !element.hasAttribute("hidden") && element.getAttribute("aria-hidden") !== "true";
  });
}

type UseModalFocusTrapOptions = {
  isOpen: boolean;
  containerRef: RefObject<HTMLElement | null>;
  getInitialFocus?: () => HTMLElement | null;
  onEscape?: () => void;
};

export function useModalFocusTrap({
  isOpen,
  containerRef,
  getInitialFocus,
  onEscape,
}: UseModalFocusTrapOptions) {
  useEffect(() => {
    if (!isOpen) return;

    const previousFocusedElement =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;

    window.requestAnimationFrame(() => {
      const container = containerRef.current;
      if (!container) return;
      const initialFocus = getInitialFocus?.() ?? getFocusableElements(container)[0] ?? container;
      initialFocus.focus();
    });

    const onKeyDown = (event: KeyboardEvent) => {
      const container = containerRef.current;
      if (!container) return;

      if (event.key === "Escape" && onEscape) {
        event.preventDefault();
        onEscape();
        return;
      }

      if (event.key !== "Tab") return;

      const focusable = getFocusableElements(container);
      if (focusable.length === 0) {
        event.preventDefault();
        container.focus();
        return;
      }

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const activeElement = document.activeElement instanceof HTMLElement ? document.activeElement : null;

      if (event.shiftKey && (!activeElement || activeElement === first || !container.contains(activeElement))) {
        event.preventDefault();
        last.focus();
        return;
      }

      if (!event.shiftKey && (!activeElement || activeElement === last || !container.contains(activeElement))) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      if (previousFocusedElement?.isConnected) {
        previousFocusedElement.focus();
      }
    };
  }, [containerRef, getInitialFocus, isOpen, onEscape]);
}
