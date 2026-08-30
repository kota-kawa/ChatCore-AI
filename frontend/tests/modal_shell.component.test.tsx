import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ModalShell } from "../components/ui/modal_shell";

function renderShell(overrides: Partial<Parameters<typeof ModalShell>[0]> = {}) {
  const onClose = overrides.onClose ?? vi.fn();
  render(
    <div className="host">
      <ModalShell
        isOpen
        onClose={onClose}
        labelledBy="shell-title"
        id="test-modal"
        className="demo-modal custom-modal"
        initialFocusSelector="[data-autofocus]"
        {...overrides}
      >
        <div className="demo-modal__content">
          <h2 id="shell-title">タイトル</h2>
          <button type="button" data-autofocus>
            OK
          </button>
        </div>
      </ModalShell>
    </div>,
  );
  return { onClose };
}

describe("ModalShell", () => {
  it("portals the dialog to <body> so it escapes any containing block", () => {
    renderShell();
    const dialog = screen.getByRole("dialog");
    // 生成UIページの .chat-page-stage は perspective を持ち、position: fixed の
    // 包含ブロックを作る。body 直下へポータルすることで、そこから使っても
    // オーバーレイが画面全体を覆える。
    expect(dialog.parentElement).toBe(document.body);
    expect(dialog).not.toBeNull();
    expect(document.querySelector(".host")?.contains(dialog)).toBe(false);
  });

  it("keeps the shared modal-base surface and merges caller classes/id", () => {
    renderShell();
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("id", "test-modal");
    expect(dialog).toHaveClass("modal-base", "is-open", "demo-modal", "custom-modal");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAttribute("aria-labelledby", "shell-title");
    expect(dialog).toHaveAttribute("aria-hidden", "false");
  });

  it("drops is-open and hides from assistive tech while closed", () => {
    renderShell({ isOpen: false });
    const dialog = screen.getByRole("dialog", { hidden: true });
    expect(dialog).not.toHaveClass("is-open");
    expect(dialog).toHaveAttribute("aria-hidden", "true");
  });

  it("closes on backdrop click but not on clicks inside the panel", () => {
    const { onClose } = renderShell();
    const dialog = screen.getByRole("dialog");

    fireEvent.click(screen.getByRole("button", { name: "OK" }));
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.click(dialog);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes on Escape", () => {
    const { onClose } = renderShell();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("blocks backdrop click and Escape while dismissDisabled", () => {
    const { onClose } = renderShell({ dismissDisabled: true });
    fireEvent.click(screen.getByRole("dialog"));
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
  });

  it("moves focus to the requested initial target on open", async () => {
    renderShell();
    const okButton = screen.getByRole("button", { name: "OK" });
    await vi.waitFor(() => expect(okButton).toHaveFocus());
  });
});
