import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AuthMessageModal } from "../components/auth/auth_gateway_modules/components/auth_message_modal";

function renderModal(overrides: Partial<Parameters<typeof AuthMessageModal>[0]> = {}) {
  const onHide = overrides.onHide ?? vi.fn();
  render(
    <AuthMessageModal
      isModalClosing={false}
      message="コードを送信しました"
      onHide={onHide}
      {...overrides}
    />,
  );
  return { onHide };
}

// 認証メッセージモーダルは共通ModalShellへ乗せ、role/aria/フォーカストラップ/Escapeを
// 独自実装せず共通部品に委ねている前提を固定する。
// Locks in that the auth message modal rides on the shared ModalShell for role/aria/focus
// trap/Escape instead of a bespoke implementation.
describe("AuthMessageModal", () => {
  it("renders as an accessible dialog labelled by the message", () => {
    renderModal();
    const dialog = screen.getByRole("dialog");

    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAttribute("aria-labelledby", "modalMessage");
    expect(dialog).toHaveAttribute("aria-hidden", "false");
    expect(dialog).toHaveClass("modal-base", "is-open", "auth-message-modal");
    expect(dialog.parentElement).toBe(document.body);
    expect(screen.getByText("コードを送信しました")).toHaveAttribute("id", "modalMessage");
  });

  it("hides from assistive tech and drops is-open while there is no message", () => {
    renderModal({ message: null });
    const dialog = screen.getByRole("dialog", { hidden: true });

    expect(dialog).toHaveAttribute("aria-hidden", "true");
    expect(dialog).not.toHaveClass("is-open");
  });

  it("moves initial focus to the close button", async () => {
    renderModal();
    const closeButton = screen.getByRole("button", { name: "閉じる" });
    await vi.waitFor(() => expect(closeButton).toHaveFocus());
  });

  it("closes on Escape and on backdrop click, but not on a click inside the panel", () => {
    const { onHide } = renderModal();
    const dialog = screen.getByRole("dialog");

    fireEvent.click(screen.getByText("コードを送信しました"));
    expect(onHide).not.toHaveBeenCalled();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(onHide).toHaveBeenCalledTimes(1);

    fireEvent.click(dialog);
    expect(onHide).toHaveBeenCalledTimes(2);
  });

  it("keeps the hide-animation class while the modal is closing", () => {
    renderModal({ isModalClosing: true });
    expect(screen.getByRole("dialog")).toHaveClass("hide-animation");
  });
});
