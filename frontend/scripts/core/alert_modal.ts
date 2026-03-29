const ALERT_MODAL_ROOT_ID = "cc-alert-modal-root";
const CONFIRM_MODAL_ROOT_ID = "cc-confirm-modal-root";
const ALERT_MODAL_OPEN_CLASS = "cc-alert-modal-open";

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

    const root = document.createElement("div");
    root.id = ALERT_MODAL_ROOT_ID;
    root.className = "cc-alert-modal";
    root.setAttribute("role", "dialog");
    root.setAttribute("aria-modal", "true");
    root.setAttribute("aria-hidden", "true");
    root.hidden = true;
    root.innerHTML = `
      <div class="cc-alert-modal__overlay" data-cc-alert-close></div>
      <div class="cc-alert-modal__dialog" role="document" tabindex="-1">
        <button type="button" class="cc-alert-modal__close" aria-label="閉じる">×</button>
        <h2 class="cc-alert-modal__title">お知らせ</h2>
        <p class="cc-alert-modal__message"></p>
        <div class="cc-alert-modal__actions">
          <button type="button" class="cc-alert-modal__button">OK</button>
        </div>
      </div>
    `;
    document.body.appendChild(root);
    return root;
  }

  private bindEvents() {
    this.rootEl.addEventListener("click", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) return;
      if (target.hasAttribute("data-cc-alert-close")) {
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

    this.previouslyFocusedElement =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    this.messageEl.textContent = nextMessage;
    this.rootEl.hidden = false;
    this.rootEl.setAttribute("aria-hidden", "false");
    this.rootEl.classList.add("is-visible");
    document.body.classList.add(ALERT_MODAL_OPEN_CLASS);
    this.isVisible = true;
    this.okBtn.focus();
  }

  private closeCurrent() {
    if (!this.isVisible) return;

    this.rootEl.classList.remove("is-visible");
    this.rootEl.setAttribute("aria-hidden", "true");
    this.rootEl.hidden = true;
    this.isVisible = false;
    releaseBodyModalState();

    if (this.previouslyFocusedElement?.isConnected) {
      this.previouslyFocusedElement.focus();
    }
    this.previouslyFocusedElement = null;

    this.openNext();
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

  constructor() {
    this.rootEl = this.createModalElement();

    const messageEl = this.rootEl.querySelector(".cc-alert-modal__message");
    const closeBtn = this.rootEl.querySelector(".cc-alert-modal__close");
    const cancelBtn = this.rootEl.querySelector('[data-cc-confirm-cancel="true"]');
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

    const root = document.createElement("div");
    root.id = CONFIRM_MODAL_ROOT_ID;
    root.className = "cc-alert-modal cc-alert-modal--confirm";
    root.setAttribute("role", "dialog");
    root.setAttribute("aria-modal", "true");
    root.setAttribute("aria-hidden", "true");
    root.hidden = true;
    root.innerHTML = `
      <div class="cc-alert-modal__overlay" data-cc-confirm-cancel="true"></div>
      <div class="cc-alert-modal__dialog" role="document" tabindex="-1">
        <button type="button" class="cc-alert-modal__close" aria-label="閉じる">×</button>
        <h2 class="cc-alert-modal__title">確認</h2>
        <p class="cc-alert-modal__message"></p>
        <div class="cc-alert-modal__actions">
          <button type="button" class="cc-alert-modal__button cc-alert-modal__button--secondary" data-cc-confirm-cancel="true">キャンセル</button>
          <button type="button" class="cc-alert-modal__button" data-cc-confirm-ok="true">OK</button>
        </div>
      </div>
    `;
    document.body.appendChild(root);
    return root;
  }

  private bindEvents() {
    this.rootEl.addEventListener("click", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) return;
      if (target.getAttribute("data-cc-confirm-cancel") === "true") {
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

    this.previouslyFocusedElement =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    this.messageEl.textContent = nextItem.message;
    this.rootEl.hidden = false;
    this.rootEl.setAttribute("aria-hidden", "false");
    this.rootEl.classList.add("is-visible");
    document.body.classList.add(ALERT_MODAL_OPEN_CLASS);
    this.isVisible = true;
    this.cancelBtn.focus();
  }

  private finish(confirmed: boolean) {
    if (!this.isVisible) return;

    this.rootEl.classList.remove("is-visible");
    this.rootEl.setAttribute("aria-hidden", "true");
    this.rootEl.hidden = true;
    this.isVisible = false;
    releaseBodyModalState();

    const activeItem = this.currentItem;
    this.currentItem = null;
    if (activeItem) {
      activeItem.resolve(confirmed);
    }

    if (this.previouslyFocusedElement?.isConnected) {
      this.previouslyFocusedElement.focus();
    }
    this.previouslyFocusedElement = null;

    this.openNext();
  }
}

type DialogWindow = typeof window & {
  __chatcoreAlertModalInitialized?: boolean;
  __chatcoreAlertModal?: GlobalAlertModal;
  __chatcoreConfirmModalInitialized?: boolean;
  __chatcoreConfirmModal?: GlobalConfirmModal;
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

ensureGlobalAlertModal();
ensureGlobalConfirmModal();

export { showAlertModal, showConfirmModal };
