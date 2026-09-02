/**
 * Markup builders and open/close transitions for the global alert & confirm
 * dialogs. Keeps DOM/animation concerns out of the queueing logic in
 * `alert_modal.ts`.
 */

const EXIT_TRANSITION_MS = 200;

const ICONS = {
  alert: `
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" focusable="false">
      <circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="1.7" />
      <path d="M12 11.1v5.2" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" />
      <circle cx="12" cy="7.7" r="1.15" fill="currentColor" />
    </svg>
  `,
  confirm: `
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" focusable="false">
      <circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="1.7" />
      <path
        d="M9.5 9.4a2.6 2.6 0 1 1 3.4 2.5c-.62.23-.95.72-.95 1.34v.5"
        stroke="currentColor"
        stroke-width="1.7"
        stroke-linecap="round"
      />
      <circle cx="12" cy="16.6" r="1.1" fill="currentColor" />
    </svg>
  `,
  prompt: `
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" focusable="false">
      <path
        d="M4 16.5V20h3.5L18 9.5 14.5 6 4 16.5Z"
        stroke="currentColor"
        stroke-width="1.7"
        stroke-linejoin="round"
      />
      <path d="M13.3 7.2 16.8 10.7" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" />
    </svg>
  `
} as const;

type DialogVariant = keyof typeof ICONS;

type DialogMarkupOptions = {
  variant: DialogVariant;
  closeLabel: string;
  title: string;
  overlayAttribute: string;
  actionsMarkup: string;
  /**
   * Rendered full-width under the header rather than inside the icon-indented
   * text column, so inputs line up with the dialog padding and the action row.
   */
  bodyMarkup?: string;
  titleId: string;
  messageId: string;
};

function buildDialogMarkup({
  variant,
  closeLabel,
  title,
  overlayAttribute,
  actionsMarkup,
  bodyMarkup = "",
  titleId,
  messageId
}: DialogMarkupOptions) {
  const body = bodyMarkup ? `<div class="cc-alert-modal__body">${bodyMarkup}</div>` : "";
  return `
    <div class="cc-alert-modal__overlay" ${overlayAttribute}></div>
    <div class="cc-alert-modal__dialog" role="document" tabindex="-1">
      <button type="button" class="cc-alert-modal__close" aria-label="${closeLabel}">
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" focusable="false">
          <path d="m7.5 7.5 9 9m0-9-9 9" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
        </svg>
      </button>
      <div class="cc-alert-modal__head">
        <span class="cc-alert-modal__icon" aria-hidden="true">${ICONS[variant]}</span>
        <div class="cc-alert-modal__text">
          <h2 class="cc-alert-modal__title" id="${titleId}">${title}</h2>
          <p class="cc-alert-modal__message" id="${messageId}"></p>
        </div>
      </div>
      ${body}
      <div class="cc-alert-modal__actions">${actionsMarkup}</div>
    </div>
  `;
}

function buildPromptFieldMarkup(inputId: string) {
  return `
    <div class="cc-alert-modal__field">
      <label class="cc-alert-modal__field-label" for="${inputId}"></label>
      <input
        type="text"
        id="${inputId}"
        class="cc-alert-modal__input"
        data-cc-prompt-input="true"
        autocomplete="off"
        spellcheck="false"
      />
    </div>
  `;
}

function buildButtonMarkup(options: { label: string; secondary?: boolean; attributes?: string }) {
  const modifier = options.secondary ? " cc-alert-modal__button--secondary" : "";
  const attributes = options.attributes ? ` ${options.attributes}` : "";
  return `
    <button type="button" class="cc-alert-modal__button${modifier}"${attributes}>
      <span class="cc-alert-modal__label">${options.label}</span>
    </button>
  `;
}

/** Reveals the dialog, cancelling any exit transition that is still running. */
function playOpenTransition(root: HTMLElement) {
  root.classList.remove("is-closing");
  root.hidden = false;
  root.setAttribute("aria-hidden", "false");
  root.classList.add("is-visible");
}

/**
 * Plays the exit animation and hides the dialog once it finishes.
 * Returns a cancel function so a queued dialog can take over immediately.
 */
function playCloseTransition(root: HTMLElement, onFinished: () => void) {
  root.classList.remove("is-visible");
  root.classList.add("is-closing");
  root.setAttribute("aria-hidden", "true");

  const timerId = window.setTimeout(() => {
    if (!root.classList.contains("is-closing")) return;
    root.classList.remove("is-closing");
    root.hidden = true;
    onFinished();
  }, EXIT_TRANSITION_MS);

  return () => window.clearTimeout(timerId);
}

export {
  buildButtonMarkup,
  buildDialogMarkup,
  buildPromptFieldMarkup,
  playCloseTransition,
  playOpenTransition
};
