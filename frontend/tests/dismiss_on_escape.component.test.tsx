// 開いたメニューを Escape で閉じ、開くボタンへフォーカスを戻すことを検証する。
// Tests that Escape closes an open menu and returns focus to its trigger.

import { fireEvent, render, screen } from "@testing-library/react";
import { useRef, useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { ModalShell } from "../components/ui/modal_shell";
import { useDismissOnEscape } from "../hooks/use_dismiss_on_escape";

function Menu({ initiallyOpen = true, onDismiss }: { initiallyOpen?: boolean; onDismiss?: () => void }) {
  const [open, setOpen] = useState(initiallyOpen);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  useDismissOnEscape(open, () => {
    onDismiss?.();
    setOpen(false);
  }, triggerRef);
  return (
    <div>
      <button ref={triggerRef} type="button" aria-expanded={open} onClick={() => setOpen((previous) => !previous)}>
        trigger
      </button>
      {open && <button type="button">item</button>}
    </div>
  );
}

describe("useDismissOnEscape", () => {
  // メニュー内の項目にフォーカスがあっても、Escape で閉じて開くボタンへ戻る。
  // Even with focus on a menu item, Escape closes the menu and moves focus back to the trigger.
  it("closes on Escape and returns focus to the trigger", () => {
    render(<Menu />);
    screen.getByRole("button", { name: "item" }).focus();

    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });

    const trigger = screen.getByRole("button", { name: "trigger" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).toHaveFocus();
  });

  it("does nothing while the menu is closed", () => {
    const onDismiss = vi.fn();
    render(<Menu initiallyOpen={false} onDismiss={onDismiss} />);
    const other = document.body.appendChild(document.createElement("input"));
    other.focus();

    const notPrevented = fireEvent.keyDown(other, { key: "Escape" });

    expect(onDismiss).not.toHaveBeenCalled();
    // 閉じているメニューは Escape を奪わない / A closed menu does not take the key
    expect(notPrevented).toBe(true);
    expect(other).toHaveFocus();
    other.remove();
  });

  it("ignores other keys", () => {
    const onDismiss = vi.fn();
    render(<Menu onDismiss={onDismiss} />);

    fireEvent.keyDown(document.body, { key: "Enter" });

    expect(onDismiss).not.toHaveBeenCalled();
  });

  // ほかの処理がすでに扱った Escape と、IME の変換を取り消す Escape では閉じない。
  // An Escape that was already handled, or one that cancels an IME composition, does not close the menu.
  it("ignores a defaultPrevented Escape", () => {
    const onDismiss = vi.fn();
    render(<Menu onDismiss={onDismiss} />);
    const event = new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true });
    // 配送前に打ち消しておく / Cancelled before dispatch
    event.preventDefault();

    document.body.dispatchEvent(event);

    expect(onDismiss).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "trigger" })).toHaveAttribute("aria-expanded", "true");
  });

  it("ignores an Escape that cancels an IME composition", () => {
    const onDismiss = vi.fn();
    render(<Menu onDismiss={onDismiss} />);

    const notPrevented = fireEvent.keyDown(document.body, { key: "Escape", isComposing: true });

    expect(onDismiss).not.toHaveBeenCalled();
    expect(notPrevented).toBe(true);
    expect(screen.getByRole("button", { name: "trigger" })).toHaveAttribute("aria-expanded", "true");
  });

  // インラインの onDismiss が毎回変わっても、最新の関数が呼ばれる。
  // An inline onDismiss that changes every render still calls the latest one.
  it("calls the latest onDismiss", () => {
    const first = vi.fn();
    const second = vi.fn();
    function Host({ onDismiss }: { onDismiss: () => void }) {
      const triggerRef = useRef<HTMLButtonElement | null>(null);
      useDismissOnEscape(true, onDismiss, triggerRef);
      return <button ref={triggerRef} type="button">trigger</button>;
    }
    const { rerender } = render(<Host onDismiss={first} />);
    rerender(<Host onDismiss={second} />);

    fireEvent.keyDown(document.body, { key: "Escape" });

    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1);
  });

  // メニューが開いたまま ModalShell も開いているとき、Escape 1 回でメニューだけが閉じ、モーダルは残る。
  // 2 回目の Escape ではモーダルが閉じる。
  // With a menu open inside an open ModalShell, one Escape closes only the menu and leaves the modal open;
  // the second Escape closes the modal.
  it("closes only the menu when a ModalShell focus trap is also listening", () => {
    const onModalClose = vi.fn();
    function Host() {
      return (
        <ModalShell isOpen onClose={onModalClose} labelledBy="title" className="test-modal">
          <h2 id="title">title</h2>
          <Menu />
        </ModalShell>
      );
    }
    render(<Host />);
    screen.getByRole("button", { name: "item" }).focus();

    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });

    expect(screen.getByRole("button", { name: "trigger" })).toHaveAttribute("aria-expanded", "false");
    expect(onModalClose).not.toHaveBeenCalled();

    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });

    expect(onModalClose).toHaveBeenCalledTimes(1);
  });
});
