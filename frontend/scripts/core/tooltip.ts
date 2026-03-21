const TOOLTIP_OFFSET_PX = 10;
const TOOLTIP_VIEWPORT_PADDING_PX = 12;
const TOOLTIP_MAX_FALLBACK_TEXT_LENGTH = 60;

const TOOLTIP_TARGET_SELECTOR = [
  "button",
  "a[href]",
  "summary",
  "input[type='button']",
  "input[type='submit']",
  "input[type='reset']",
  "[role='button']",
  "[data-tooltip]",
  "[title]",
  "[aria-label]",
  "[tabindex]:not([tabindex='-1'])"
].join(", ");

const TOOLTIP_SOURCE_ATTR = "data-tooltip";

class GlobalTooltip {
  private tooltipEl: HTMLDivElement;
  private tooltipContentEl: HTMLDivElement;
  private activeTarget: HTMLElement | null = null;
  private suppressedTitleByElement = new WeakMap<HTMLElement, string>();
  private pendingFrame: number | null = null;

  constructor() {
    this.tooltipEl = this.createTooltipElement();
    const contentEl = this.tooltipEl.querySelector(".cc-tooltip__content");
    if (!(contentEl instanceof HTMLDivElement)) {
      throw new Error("Tooltip content element is missing.");
    }
    this.tooltipContentEl = contentEl;
    this.bindEvents();
  }

  private createTooltipElement() {
    const tooltip = document.createElement("div");
    tooltip.className = "cc-tooltip";
    tooltip.setAttribute("role", "tooltip");
    tooltip.setAttribute("aria-hidden", "true");
    tooltip.innerHTML = `<div class="cc-tooltip__content"></div>`;
    document.body.appendChild(tooltip);
    return tooltip;
  }

  private bindEvents() {
    document.addEventListener("pointerover", this.handlePointerOver, true);
    document.addEventListener("pointerout", this.handlePointerOut, true);
    document.addEventListener("focusin", this.handleFocusIn, true);
    document.addEventListener("focusout", this.handleFocusOut, true);
    document.addEventListener("pointerdown", this.handlePointerDown, true);
    document.addEventListener("keydown", this.handleKeyDown, true);
    window.addEventListener("scroll", this.queuePositionUpdate, true);
    window.addEventListener("resize", this.hideTooltip, true);
  }

  private resolveTarget(event: Event) {
    const path = typeof event.composedPath === "function" ? event.composedPath() : [];
    for (const node of path) {
      if (!(node instanceof HTMLElement)) continue;
      if (!this.isTooltipTarget(node)) continue;
      return node;
    }

    if (event.target instanceof HTMLElement && this.isTooltipTarget(event.target)) {
      return event.target;
    }
    return null;
  }

  private isTooltipTarget(element: HTMLElement) {
    if (!element.isConnected) return false;
    if (element.closest(".cc-tooltip")) return false;
    if (element.getAttribute("aria-hidden") === "true") return false;
    if (element.matches(":disabled")) return false;
    return element.matches(TOOLTIP_TARGET_SELECTOR);
  }

  private getTooltipText(target: HTMLElement) {
    const dataTooltip = target.getAttribute(TOOLTIP_SOURCE_ATTR);
    if (typeof dataTooltip === "string" && dataTooltip.trim()) {
      return dataTooltip.trim();
    }

    const rawTitle = target.getAttribute("title") ?? this.suppressedTitleByElement.get(target);
    if (typeof rawTitle === "string" && rawTitle.trim()) {
      return rawTitle.trim();
    }

    const ariaLabel = target.getAttribute("aria-label");
    if (typeof ariaLabel === "string" && ariaLabel.trim()) {
      return ariaLabel.trim();
    }

    const fallbackText = this.getFallbackText(target);
    if (fallbackText) return fallbackText;

    return "";
  }

  private getFallbackText(target: HTMLElement) {
    if (target instanceof HTMLInputElement) {
      const type = target.type.toLowerCase();
      if (type === "button" || type === "submit" || type === "reset") {
        const value = target.value.trim();
        if (value) return value;
      }
      return "";
    }

    const text = target.textContent?.replace(/\s+/g, " ").trim() ?? "";
    if (!text) return "";
    if (text.length > TOOLTIP_MAX_FALLBACK_TEXT_LENGTH) return "";
    return text;
  }

  private suppressNativeTitle(target: HTMLElement) {
    const title = target.getAttribute("title");
    if (!title || !title.trim()) return;
    this.suppressedTitleByElement.set(target, title);
    target.removeAttribute("title");
  }

  private restoreNativeTitle(target: HTMLElement) {
    const title = this.suppressedTitleByElement.get(target);
    if (!title) return;
    if (!target.hasAttribute("title")) {
      target.setAttribute("title", title);
    }
    this.suppressedTitleByElement.delete(target);
  }

  private showTooltip(target: HTMLElement, text: string) {
    if (!text) return;

    if (this.activeTarget !== target) {
      if (this.activeTarget) this.restoreNativeTitle(this.activeTarget);
      this.activeTarget = target;
      this.suppressNativeTitle(target);
    }

    this.tooltipContentEl.textContent = text;
    this.tooltipEl.classList.add("is-visible");
    this.tooltipEl.setAttribute("aria-hidden", "false");
    this.queuePositionUpdate();
  }

  private readonly hideTooltip = () => {
    if (this.pendingFrame !== null) {
      window.cancelAnimationFrame(this.pendingFrame);
      this.pendingFrame = null;
    }

    if (this.activeTarget) {
      this.restoreNativeTitle(this.activeTarget);
      this.activeTarget = null;
    }

    this.tooltipEl.classList.remove("is-visible");
    this.tooltipEl.setAttribute("aria-hidden", "true");
    this.tooltipEl.removeAttribute("data-placement");
  };

  private readonly queuePositionUpdate = () => {
    if (!this.activeTarget) return;
    if (this.pendingFrame !== null) {
      window.cancelAnimationFrame(this.pendingFrame);
    }
    this.pendingFrame = window.requestAnimationFrame(() => {
      this.pendingFrame = null;
      this.updateTooltipPosition();
    });
  };

  private nodeBelongsToTarget(node: Node, target: HTMLElement) {
    let current: Node | null = node;
    while (current) {
      if (current === target) return true;
      if (current instanceof ShadowRoot) {
        current = current.host;
      } else {
        current = current.parentNode;
      }
    }
    return false;
  }

  private updateTooltipPosition() {
    const target = this.activeTarget;
    if (!target || !target.isConnected) {
      this.hideTooltip();
      return;
    }

    const targetRect = target.getBoundingClientRect();
    if (targetRect.width === 0 && targetRect.height === 0) {
      this.hideTooltip();
      return;
    }

    const tooltipRect = this.tooltipEl.getBoundingClientRect();
    const scrollX = window.scrollX || window.pageXOffset;
    const scrollY = window.scrollY || window.pageYOffset;
    const viewportWidth = document.documentElement.clientWidth;
    const viewportHeight = document.documentElement.clientHeight;

    let placement: "top" | "bottom" = "top";
    let top = targetRect.top + scrollY - tooltipRect.height - TOOLTIP_OFFSET_PX;
    const minTop = scrollY + TOOLTIP_VIEWPORT_PADDING_PX;

    if (top < minTop) {
      placement = "bottom";
      top = targetRect.bottom + scrollY + TOOLTIP_OFFSET_PX;
    }

    const maxTop = scrollY + viewportHeight - tooltipRect.height - TOOLTIP_VIEWPORT_PADDING_PX;
    if (maxTop >= minTop) {
      top = Math.min(Math.max(top, minTop), maxTop);
    } else {
      top = minTop;
    }

    const centerX = targetRect.left + scrollX + targetRect.width / 2;
    let left = centerX - tooltipRect.width / 2;
    const minLeft = scrollX + TOOLTIP_VIEWPORT_PADDING_PX;
    const maxLeft = scrollX + viewportWidth - tooltipRect.width - TOOLTIP_VIEWPORT_PADDING_PX;
    if (maxLeft >= minLeft) {
      left = Math.min(Math.max(left, minLeft), maxLeft);
    } else {
      left = minLeft;
    }

    this.tooltipEl.style.left = `${Math.round(left)}px`;
    this.tooltipEl.style.top = `${Math.round(top)}px`;
    this.tooltipEl.setAttribute("data-placement", placement);
  }

  private readonly handlePointerOver = (event: Event) => {
    if (event instanceof PointerEvent && event.pointerType === "touch") {
      return;
    }

    const target = this.resolveTarget(event);
    if (!target) return;

    const text = this.getTooltipText(target);
    if (!text) {
      if (this.activeTarget === target) this.hideTooltip();
      return;
    }

    this.showTooltip(target, text);
  };

  private readonly handlePointerOut = (event: MouseEvent) => {
    if (!this.activeTarget) return;
    const nextTarget = event.relatedTarget;
    if (nextTarget instanceof Node && this.nodeBelongsToTarget(nextTarget, this.activeTarget)) {
      return;
    }
    this.hideTooltip();
  };

  private readonly handleFocusIn = (event: FocusEvent) => {
    const target = this.resolveTarget(event);
    if (!target) return;

    const text = this.getTooltipText(target);
    if (!text) {
      if (this.activeTarget === target) this.hideTooltip();
      return;
    }

    this.showTooltip(target, text);
  };

  private readonly handleFocusOut = (event: FocusEvent) => {
    if (!this.activeTarget) return;
    const nextTarget = event.relatedTarget;
    if (nextTarget instanceof Node && this.nodeBelongsToTarget(nextTarget, this.activeTarget)) {
      return;
    }
    this.hideTooltip();
  };

  private readonly handlePointerDown = () => {
    this.hideTooltip();
  };

  private readonly handleKeyDown = (event: KeyboardEvent) => {
    if (event.key === "Escape") {
      this.hideTooltip();
    }
  };
}

function ensureGlobalTooltip() {
  if (typeof window === "undefined") return;
  if (typeof document === "undefined") return;

  const globalWindow = window as typeof window & { __chatcoreTooltipInitialized?: boolean };
  if (globalWindow.__chatcoreTooltipInitialized) return;

  if (!document.body) {
    document.addEventListener("DOMContentLoaded", ensureGlobalTooltip, { once: true });
    return;
  }

  new GlobalTooltip();
  globalWindow.__chatcoreTooltipInitialized = true;
}

ensureGlobalTooltip();

export {};
