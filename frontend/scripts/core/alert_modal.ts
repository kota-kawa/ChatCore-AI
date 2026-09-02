import { getRuntimeLocale } from "../../lib/i18n/config";
import {
  buildButtonMarkup,
  buildDialogMarkup,
  buildPromptFieldMarkup,
  playCloseTransition,
  playOpenTransition
} from "./alert_modal_view";

const ALERT_MODAL_ROOT_ID = "cc-alert-modal-root";
const CONFIRM_MODAL_ROOT_ID = "cc-confirm-modal-root";
const PROMPT_MODAL_ROOT_ID = "cc-prompt-modal-root";
const ALERT_MODAL_OPEN_CLASS = "cc-alert-modal-open";
const PROMPT_INPUT_ID = "cc-prompt-modal-input";

/** Wires `aria-labelledby` / `aria-describedby` so screen readers announce the dialog. */
function applyDialogAria(root: HTMLElement, titleId: string, messageId: string) {
  root.setAttribute("aria-labelledby", titleId);
  root.setAttribute("aria-describedby", messageId);
}

function releaseBodyModalState() {
  if (document.querySelector(".cc-alert-modal.is-visible")) return;
  document.body.classList.remove(ALERT_MODAL_OPEN_CLASS);
}

class GlobalAlertModal {
  private readonly rootEl: HTMLDivElement;
  private readonly messageEl: HTMLParagraphElement;
  private readonly closeBtn: HTMLButtonElement;
  private readonly okBtn: HTMLButtonElement;
  private readonly queue: string[] = [];
  private isVisible = false;
  private previouslyFocusedElement: HTMLElement | null = null;
  private cancelExitTransition: (() => void) | null = null;

  constructor() {
    this.rootEl = this.createModalElement();

    const messageEl = this.rootEl.querySelector(".cc-alert-modal__message");
    const closeBtn = this.rootEl.querySelector(".cc-alert-modal__close");
    const okBtn = this.rootEl.querySelector(".cc-alert-modal__button");

    if (
      !(messageEl instanceof HTMLParagraphElement) ||
      !(closeBtn instanceof HTMLButtonElement) ||
      !(okBtn instanceof HTMLButtonElement)
    ) {
      throw new Error("Alert modal elements are missing.");
    }

    this.messageEl = messageEl;
    this.closeBtn = closeBtn;
    this.okBtn = okBtn;
    this.bindEvents();
  }

  public readonly alert = (message?: unknown) => {
    this.queue.push(this.normalizeMessage(message));
    this.openNext();
  };

  private normalizeMessage(message?: unknown) {
    if (message === undefined) return "";
    return String(message);
  }

  private createModalElement() {
    const existing = document.getElementById(ALERT_MODAL_ROOT_ID);
    if (existing instanceof HTMLDivElement) {
      return existing;
    }

    const english = getRuntimeLocale() === "en";
    const root = document.createElement("div");
    root.id = ALERT_MODAL_ROOT_ID;
    root.className = "cc-alert-modal";
    root.setAttribute("role", "dialog");
    root.setAttribute("aria-modal", "true");
    root.setAttribute("aria-hidden", "true");
    root.hidden = true;
    root.innerHTML = buildDialogMarkup({
      variant: "alert",
      closeLabel: english ? "Close" : "閉じる",
      title: english ? "Notice" : "お知らせ",
      overlayAttribute: "data-cc-alert-close",
      titleId: "cc-alert-modal-title",
      messageId: "cc-alert-modal-message",
      actionsMarkup: buildButtonMarkup({ label: "OK" })
    });
    applyDialogAria(root, "cc-alert-modal-title", "cc-alert-modal-message");
    document.body.appendChild(root);
    return root;
  }

  private bindEvents() {
    this.rootEl.addEventListener("click", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) return;
      if (target.closest("[data-cc-alert-close]")) {
        this.closeCurrent();
      }
    });
    this.closeBtn.addEventListener("click", () => this.closeCurrent());
    this.okBtn.addEventListener("click", () => this.closeCurrent());
    document.addEventListener("keydown", this.handleKeyDown, true);
  }

  private readonly handleKeyDown = (event: KeyboardEvent) => {
    if (!this.isVisible) return;

    if (event.key === "Escape" || event.key === "Enter") {
      event.preventDefault();
      this.closeCurrent();
      return;
    }

    if (event.key !== "Tab") return;

    const focusable = this.getFocusableElements();
    if (focusable.length === 0) return;

    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement;

    if (event.shiftKey && active === first) {
      event.preventDefault();
      last.focus();
      return;
    }

    if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  };

  private getFocusableElements() {
    const candidates = this.rootEl.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    return Array.from(candidates).filter((el) => !el.hasAttribute("disabled"));
  }

  private openNext() {
    if (this.isVisible) return;
    const nextMessage = this.queue.shift();
    if (nextMessage === undefined) return;

    this.cancelExitTransition?.();
    this.cancelExitTransition = null;

    this.previouslyFocusedElement =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    this.messageEl.textContent = nextMessage;
    playOpenTransition(this.rootEl);
    document.body.classList.add(ALERT_MODAL_OPEN_CLASS);
    this.isVisible = true;
    this.okBtn.focus();
  }

  private closeCurrent() {
    if (!this.isVisible) return;

    this.isVisible = false;
    this.cancelExitTransition = playCloseTransition(this.rootEl, () => {
      this.cancelExitTransition = null;
      releaseBodyModalState();
      this.openNext();
    });

    if (this.previouslyFocusedElement?.isConnected) {
      this.previouslyFocusedElement.focus();
    }
    this.previouslyFocusedElement = null;
  }
}

type ConfirmQueueItem = {
  message: string;
  resolve: (confirmed: boolean) => void;
};

class GlobalConfirmModal {
  private readonly rootEl: HTMLDivElement;
  private readonly messageEl: HTMLParagraphElement;
  private readonly closeBtn: HTMLButtonElement;
  private readonly cancelBtn: HTMLButtonElement;
  private readonly okBtn: HTMLButtonElement;
  private readonly queue: ConfirmQueueItem[] = [];
  private currentItem: ConfirmQueueItem | null = null;
  private isVisible = false;
  private previouslyFocusedElement: HTMLElement | null = null;
  private cancelExitTransition: (() => void) | null = null;

  constructor() {
    this.rootEl = this.createModalElement();

    const messageEl = this.rootEl.querySelector(".cc-alert-modal__message");
    const closeBtn = this.rootEl.querySelector(".cc-alert-modal__close");
    const cancelBtn = this.rootEl.querySelector('button[data-cc-confirm-cancel="true"]');
    const okBtn = this.rootEl.querySelector('[data-cc-confirm-ok="true"]');

    if (
      !(messageEl instanceof HTMLParagraphElement) ||
      !(closeBtn instanceof HTMLButtonElement) ||
      !(cancelBtn instanceof HTMLButtonElement) ||
      !(okBtn instanceof HTMLButtonElement)
    ) {
      throw new Error("Confirm modal elements are missing.");
    }

    this.messageEl = messageEl;
    this.closeBtn = closeBtn;
    this.cancelBtn = cancelBtn;
    this.okBtn = okBtn;
    this.bindEvents();
  }

  public readonly confirm = (message?: unknown): Promise<boolean> => {
    const normalizedMessage = message === undefined ? "" : String(message);
    return new Promise<boolean>((resolve) => {
      this.queue.push({
        message: normalizedMessage,
        resolve
      });
      this.openNext();
    });
  };

  private createModalElement() {
    const existing = document.getElementById(CONFIRM_MODAL_ROOT_ID);
    if (existing instanceof HTMLDivElement) {
      return existing;
    }

    const english = getRuntimeLocale() === "en";
    const root = document.createElement("div");
    root.id = CONFIRM_MODAL_ROOT_ID;
    root.className = "cc-alert-modal cc-alert-modal--confirm";
    root.setAttribute("role", "dialog");
    root.setAttribute("aria-modal", "true");
    root.setAttribute("aria-hidden", "true");
    root.hidden = true;
    root.innerHTML = buildDialogMarkup({
      variant: "confirm",
      closeLabel: english ? "Close" : "閉じる",
      title: english ? "Confirm" : "確認",
      overlayAttribute: 'data-cc-confirm-cancel="true"',
      titleId: "cc-confirm-modal-title",
      messageId: "cc-confirm-modal-message",
      actionsMarkup: [
        buildButtonMarkup({
          label: english ? "Cancel" : "キャンセル",
          secondary: true,
          attributes: 'data-cc-confirm-cancel="true"'
        }),
        buildButtonMarkup({
          label: "OK",
          attributes: 'data-cc-confirm-ok="true"'
        })
      ].join("")
    });
    applyDialogAria(root, "cc-confirm-modal-title", "cc-confirm-modal-message");
    document.body.appendChild(root);
    return root;
  }

  private bindEvents() {
    this.rootEl.addEventListener("click", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) return;
      if (target.closest('[data-cc-confirm-cancel="true"]')) {
        this.finish(false);
      }
    });
    this.closeBtn.addEventListener("click", () => this.finish(false));
    this.cancelBtn.addEventListener("click", () => this.finish(false));
    this.okBtn.addEventListener("click", () => this.finish(true));
    document.addEventListener("keydown", this.handleKeyDown, true);
  }

  private readonly handleKeyDown = (event: KeyboardEvent) => {
    if (!this.isVisible) return;

    if (event.key === "Escape") {
      event.preventDefault();
      this.finish(false);
      return;
    }

    if (event.key === "Enter") {
      event.preventDefault();
      this.finish(true);
      return;
    }

    if (event.key !== "Tab") return;

    const focusable = this.getFocusableElements();
    if (focusable.length === 0) return;

    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement;

    if (event.shiftKey && active === first) {
      event.preventDefault();
      last.focus();
      return;
    }

    if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  };

  private getFocusableElements() {
    const candidates = this.rootEl.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    return Array.from(candidates).filter((el) => !el.hasAttribute("disabled"));
  }

  private openNext() {
    if (this.isVisible) return;

    const nextItem = this.queue.shift();
    if (!nextItem) return;
    this.currentItem = nextItem;

    this.cancelExitTransition?.();
    this.cancelExitTransition = null;

    this.previouslyFocusedElement =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    this.messageEl.textContent = nextItem.message;
    playOpenTransition(this.rootEl);
    document.body.classList.add(ALERT_MODAL_OPEN_CLASS);
    this.isVisible = true;
    this.cancelBtn.focus();
  }

  private finish(confirmed: boolean) {
    if (!this.isVisible) return;

    this.isVisible = false;
    this.cancelExitTransition = playCloseTransition(this.rootEl, () => {
      this.cancelExitTransition = null;
      releaseBodyModalState();
      this.openNext();
    });

    const activeItem = this.currentItem;
    this.currentItem = null;
    if (activeItem) {
      activeItem.resolve(confirmed);
    }

    if (this.previouslyFocusedElement?.isConnected) {
      this.previouslyFocusedElement.focus();
    }
    this.previouslyFocusedElement = null;
  }
}

/**
 * `message` is the field label (it maps 1:1 onto `window.prompt(message)`), so
 * anything longer belongs in `description` to keep the label scannable.
 */
type PromptModalOptions = {
  title?: string;
  description?: string;
  defaultValue?: string;
  placeholder?: string;
  confirmLabel?: string;
  cancelLabel?: string;
};

type PromptQueueItem = {
  message: string;
  options: PromptModalOptions;
  resolve: (value: string | null) => void;
};

class GlobalPromptModal {
  private readonly rootEl: HTMLDivElement;
  private readonly titleEl: HTMLElement;
  private readonly messageEl: HTMLParagraphElement;
  private readonly inputEl: HTMLInputElement;
  private readonly inputLabelEl: HTMLElement;
  private readonly closeBtn: HTMLButtonElement;
  private readonly cancelBtn: HTMLButtonElement;
  private readonly okBtn: HTMLButtonElement;
  private readonly okLabelEl: HTMLElement;
  private readonly cancelLabelEl: HTMLElement;
  private readonly queue: PromptQueueItem[] = [];
  private currentItem: PromptQueueItem | null = null;
  private isVisible = false;
  private previouslyFocusedElement: HTMLElement | null = null;
  private cancelExitTransition: (() => void) | null = null;

  constructor() {
    this.rootEl = this.createModalElement();

    const titleEl = this.rootEl.querySelector(".cc-alert-modal__title");
    const messageEl = this.rootEl.querySelector(".cc-alert-modal__message");
    const inputEl = this.rootEl.querySelector('input[data-cc-prompt-input="true"]');
    const inputLabelEl = this.rootEl.querySelector(".cc-alert-modal__field-label");
    const closeBtn = this.rootEl.querySelector(".cc-alert-modal__close");
    const cancelBtn = this.rootEl.querySelector('button[data-cc-prompt-cancel="true"]');
    const okBtn = this.rootEl.querySelector('[data-cc-prompt-ok="true"]');

    if (
      !(titleEl instanceof HTMLElement) ||
      !(messageEl instanceof HTMLParagraphElement) ||
      !(inputEl instanceof HTMLInputElement) ||
      !(inputLabelEl instanceof HTMLElement) ||
      !(closeBtn instanceof HTMLButtonElement) ||
      !(cancelBtn instanceof HTMLButtonElement) ||
      !(okBtn instanceof HTMLButtonElement)
    ) {
      throw new Error("Prompt modal elements are missing.");
    }

    const okLabelEl = okBtn.querySelector(".cc-alert-modal__label");
    const cancelLabelEl = cancelBtn.querySelector(".cc-alert-modal__label");
    if (!(okLabelEl instanceof HTMLElement) || !(cancelLabelEl instanceof HTMLElement)) {
      throw new Error("Prompt modal button labels are missing.");
    }

    this.titleEl = titleEl;
    this.messageEl = messageEl;
    this.inputEl = inputEl;
    this.inputLabelEl = inputLabelEl;
    this.closeBtn = closeBtn;
    this.cancelBtn = cancelBtn;
    this.okBtn = okBtn;
    this.okLabelEl = okLabelEl;
    this.cancelLabelEl = cancelLabelEl;
    this.bindEvents();
  }

  public readonly prompt = (message?: unknown, options: PromptModalOptions = {}): Promise<string | null> => {
    const normalizedMessage = message === undefined ? "" : String(message);
    return new Promise<string | null>((resolve) => {
      this.queue.push({ message: normalizedMessage, options, resolve });
      this.openNext();
    });
  };

  private createModalElement() {
    const existing = document.getElementById(PROMPT_MODAL_ROOT_ID);
    if (existing instanceof HTMLDivElement) {
      return existing;
    }

    const english = getRuntimeLocale() === "en";
    const root = document.createElement("div");
    root.id = PROMPT_MODAL_ROOT_ID;
    root.className = "cc-alert-modal cc-alert-modal--prompt";
    root.setAttribute("role", "dialog");
    root.setAttribute("aria-modal", "true");
    root.setAttribute("aria-hidden", "true");
    root.hidden = true;
    root.innerHTML = buildDialogMarkup({
      variant: "prompt",
      closeLabel: english ? "Close" : "閉じる",
      title: english ? "Input" : "入力",
      overlayAttribute: 'data-cc-prompt-cancel="true"',
      titleId: "cc-prompt-modal-title",
      messageId: "cc-prompt-modal-message",
      bodyMarkup: buildPromptFieldMarkup(PROMPT_INPUT_ID),
      actionsMarkup: [
        buildButtonMarkup({
          label: english ? "Cancel" : "キャンセル",
          secondary: true,
          attributes: 'data-cc-prompt-cancel="true"'
        }),
        buildButtonMarkup({
          label: "OK",
          attributes: 'data-cc-prompt-ok="true"'
        })
      ].join("")
    });
    applyDialogAria(root, "cc-prompt-modal-title", "cc-prompt-modal-message");
    document.body.appendChild(root);
    return root;
  }

  private bindEvents() {
    this.rootEl.addEventListener("click", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) return;
      if (target.closest('[data-cc-prompt-cancel="true"]')) {
        this.finish(null);
      }
    });
    this.closeBtn.addEventListener("click", () => this.finish(null));
    this.cancelBtn.addEventListener("click", () => this.finish(null));
    this.okBtn.addEventListener("click", () => this.finish(this.inputEl.value));
    document.addEventListener("keydown", this.handleKeyDown, true);
  }

  private readonly handleKeyDown = (event: KeyboardEvent) => {
    if (!this.isVisible) return;

    if (event.key === "Escape") {
      event.preventDefault();
      this.finish(null);
      return;
    }

    if (event.key === "Enter") {
      event.preventDefault();
      this.finish(this.inputEl.value);
      return;
    }

    if (event.key !== "Tab") return;

    const focusable = this.getFocusableElements();
    if (focusable.length === 0) return;

    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement;

    if (event.shiftKey && active === first) {
      event.preventDefault();
      last.focus();
      return;
    }

    if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  };

  private getFocusableElements() {
    const candidates = this.rootEl.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    return Array.from(candidates).filter((el) => !el.hasAttribute("disabled"));
  }

  private openNext() {
    if (this.isVisible) return;

    const nextItem = this.queue.shift();
    if (!nextItem) return;
    this.currentItem = nextItem;

    this.cancelExitTransition?.();
    this.cancelExitTransition = null;

    const english = getRuntimeLocale() === "en";
    const { options } = nextItem;

    this.previouslyFocusedElement =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    // The message is the field label, so the header keeps a short title and the
    // paragraph is reserved for optional extra context (hidden while empty).
    this.titleEl.textContent = options.title || (english ? "Input" : "入力");
    this.messageEl.textContent = options.description ?? "";
    this.inputLabelEl.textContent = nextItem.message || (english ? "Value" : "入力内容");
    this.okLabelEl.textContent = options.confirmLabel ?? "OK";
    this.cancelLabelEl.textContent =
      options.cancelLabel ?? (english ? "Cancel" : "キャンセル");
    this.inputEl.value = options.defaultValue ?? "";
    this.inputEl.placeholder = options.placeholder ?? "";

    playOpenTransition(this.rootEl);
    document.body.classList.add(ALERT_MODAL_OPEN_CLASS);
    this.isVisible = true;
    this.inputEl.focus();
    this.inputEl.select();
  }

  private finish(rawValue: string | null) {
    if (!this.isVisible) return;

    this.isVisible = false;
    this.cancelExitTransition = playCloseTransition(this.rootEl, () => {
      this.cancelExitTransition = null;
      releaseBodyModalState();
      this.openNext();
    });

    const activeItem = this.currentItem;
    this.currentItem = null;
    activeItem?.resolve(rawValue);

    if (this.previouslyFocusedElement?.isConnected) {
      this.previouslyFocusedElement.focus();
    }
    this.previouslyFocusedElement = null;
  }
}

type DialogWindow = typeof window & {
  __chatcoreAlertModalInitialized?: boolean;
  __chatcoreAlertModal?: GlobalAlertModal;
  __chatcoreConfirmModalInitialized?: boolean;
  __chatcoreConfirmModal?: GlobalConfirmModal;
  __chatcorePromptModalInitialized?: boolean;
  __chatcorePromptModal?: GlobalPromptModal;
};

function ensureGlobalAlertModal() {
  if (typeof window === "undefined") return;
  if (typeof document === "undefined") return;

  const globalWindow = window as DialogWindow;
  if (globalWindow.__chatcoreAlertModalInitialized) return;

  const install = () => {
    if (globalWindow.__chatcoreAlertModalInitialized) return;
    const alertModal = new GlobalAlertModal();
    globalWindow.__chatcoreAlertModal = alertModal;
    window.alert = alertModal.alert;
    globalWindow.__chatcoreAlertModalInitialized = true;
  };

  if (!document.body) {
    document.addEventListener("DOMContentLoaded", install, { once: true });
    return;
  }

  install();
}

function ensureGlobalConfirmModal() {
  if (typeof window === "undefined") return;
  if (typeof document === "undefined") return;

  const globalWindow = window as DialogWindow;
  if (globalWindow.__chatcoreConfirmModalInitialized) return;

  const install = () => {
    if (globalWindow.__chatcoreConfirmModalInitialized) return;
    globalWindow.__chatcoreConfirmModal = new GlobalConfirmModal();
    globalWindow.__chatcoreConfirmModalInitialized = true;
  };

  if (!document.body) {
    document.addEventListener("DOMContentLoaded", install, { once: true });
    return;
  }

  install();
}

function ensureGlobalPromptModal() {
  if (typeof window === "undefined") return;
  if (typeof document === "undefined") return;

  const globalWindow = window as DialogWindow;
  if (globalWindow.__chatcorePromptModalInitialized) return;

  const install = () => {
    if (globalWindow.__chatcorePromptModalInitialized) return;
    globalWindow.__chatcorePromptModal = new GlobalPromptModal();
    globalWindow.__chatcorePromptModalInitialized = true;
  };

  if (!document.body) {
    document.addEventListener("DOMContentLoaded", install, { once: true });
    return;
  }

  install();
}

function showAlertModal(message?: unknown) {
  if (typeof window === "undefined") return;
  ensureGlobalAlertModal();
  (window as DialogWindow).__chatcoreAlertModal?.alert(message);
}

function showConfirmModal(message?: unknown): Promise<boolean> {
  if (typeof window === "undefined") {
    return Promise.resolve(false);
  }
  ensureGlobalConfirmModal();
  return (window as DialogWindow).__chatcoreConfirmModal?.confirm(message) ?? Promise.resolve(false);
}

function showPromptModal(message?: unknown, options: PromptModalOptions = {}): Promise<string | null> {
  if (typeof window === "undefined") {
    return Promise.resolve(null);
  }
  ensureGlobalPromptModal();
  return (
    (window as DialogWindow).__chatcorePromptModal?.prompt(message, options) ?? Promise.resolve(null)
  );
}

ensureGlobalAlertModal();
ensureGlobalConfirmModal();
ensureGlobalPromptModal();

export { showAlertModal, showConfirmModal, showPromptModal };
export type { PromptModalOptions };
