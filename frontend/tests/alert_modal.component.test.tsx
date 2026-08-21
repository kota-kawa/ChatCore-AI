import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { showAlertModal, showConfirmModal } from "../scripts/core/alert_modal";

const CONFIRM_ROOT = "#cc-confirm-modal-root";
const ALERT_ROOT = "#cc-alert-modal-root";

function root(selector: string) {
  const el = document.querySelector<HTMLDivElement>(selector);
  if (!el) throw new Error(`${selector} is missing`);
  return el;
}

function button(selector: string, attribute: string) {
  const el = root(selector).querySelector<HTMLButtonElement>(`button[${attribute}]`);
  if (!el) throw new Error(`button[${attribute}] is missing`);
  return el;
}

describe("global alert & confirm modal", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    // The dialogs are process-wide singletons, so drain anything a test left open.
    for (let i = 0; i < 5; i += 1) {
      document
        .querySelector<HTMLButtonElement>(`${CONFIRM_ROOT} button[data-cc-confirm-cancel="true"]`)
        ?.click();
      document.querySelector<HTMLButtonElement>(`${ALERT_ROOT} .cc-alert-modal__button`)?.click();
      vi.runOnlyPendingTimers();
    }
    vi.useRealTimers();
  });

  it("renders the confirm dialog with a labelled icon-less description and both actions", () => {
    void showConfirmModal("削除しますか？");

    const dialog = root(CONFIRM_ROOT);
    expect(dialog.classList.contains("is-visible")).toBe(true);
    expect(dialog.getAttribute("aria-hidden")).toBe("false");
    expect(dialog.querySelector(".cc-alert-modal__message")?.textContent).toBe("削除しますか？");
    expect(dialog.querySelector(".cc-alert-modal__icon svg")).not.toBeNull();

    const cancel = button(CONFIRM_ROOT, 'data-cc-confirm-cancel="true"');
    const ok = button(CONFIRM_ROOT, 'data-cc-confirm-ok="true"');
    expect(cancel.querySelector(".cc-alert-modal__label")?.textContent).toBe("キャンセル");
    expect(cancel.querySelector(".cc-alert-modal__hint")?.textContent).toBe("Esc");
    expect(ok.querySelector(".cc-alert-modal__label")?.textContent).toBe("OK");
    expect(ok.querySelector(".cc-alert-modal__hint")?.textContent).toBe("Enter");
  });


  it("resolves true from OK and plays the exit transition before hiding", async () => {
    const pending = showConfirmModal("保存しますか？");
    button(CONFIRM_ROOT, 'data-cc-confirm-ok="true"').click();

    await expect(pending).resolves.toBe(true);

    const dialog = root(CONFIRM_ROOT);
    expect(dialog.classList.contains("is-visible")).toBe(false);
    expect(dialog.classList.contains("is-closing")).toBe(true);
    expect(dialog.hidden).toBe(false);

    vi.runOnlyPendingTimers();
    expect(dialog.classList.contains("is-closing")).toBe(false);
    expect(dialog.hidden).toBe(true);
    expect(document.body.classList.contains("cc-alert-modal-open")).toBe(false);
  });

  it("resolves false when the label inside the cancel button is clicked", async () => {
    const pending = showConfirmModal("破棄しますか？");
    const label = button(CONFIRM_ROOT, 'data-cc-confirm-cancel="true"').querySelector<HTMLElement>(
      ".cc-alert-modal__label"
    );
    label?.click();

    await expect(pending).resolves.toBe(false);
    vi.runOnlyPendingTimers();
  });

  it("shows the next queued alert once the previous one finished closing", () => {
    showAlertModal("ひとつめ");
    showAlertModal("ふたつめ");

    const dialog = root(ALERT_ROOT);
    const message = dialog.querySelector(".cc-alert-modal__message");
    expect(message?.textContent).toBe("ひとつめ");

    dialog.querySelector<HTMLButtonElement>(".cc-alert-modal__button")?.click();
    expect(message?.textContent).toBe("ひとつめ");

    vi.runOnlyPendingTimers();
    expect(message?.textContent).toBe("ふたつめ");
    expect(dialog.classList.contains("is-visible")).toBe(true);
    expect(dialog.hidden).toBe(false);
  });
});
