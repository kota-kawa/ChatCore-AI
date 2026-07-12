import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DraggableModal } from "../components/ui/DraggableModal";

describe("DraggableModal", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("moves focus into the dialog, closes with Escape, and restores focus", () => {
    const onClose = vi.fn();
    const opener = document.createElement("button");
    document.body.append(opener);
    opener.focus();

    const { rerender } = render(
      <DraggableModal isOpen onClose={onClose} title="テストモーダル">
        <input aria-label="最初の入力" />
      </DraggableModal>
    );
    act(() => vi.advanceTimersByTime(0));

    expect(screen.getByRole("dialog", { name: "テストモーダル" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "AIエージェントを閉じる" })).toHaveFocus();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();

    rerender(
      <DraggableModal isOpen={false} onClose={onClose} title="テストモーダル">
        <input aria-label="最初の入力" />
      </DraggableModal>
    );
    expect(opener).toHaveFocus();

    act(() => vi.advanceTimersByTime(320));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    opener.remove();
  });

  it("restores and persists a safe stored position", () => {
    window.sessionStorage.setItem("agent-position", JSON.stringify({ x: 240, y: 180 }));

    render(
      <DraggableModal
        isOpen
        onClose={vi.fn()}
        title="位置保存"
        positionStorageKey="agent-position"
      >
        content
      </DraggableModal>
    );

    const dialog = screen.getByRole("dialog", { name: "位置保存" });
    expect(dialog).toHaveStyle({ left: "240px", top: "180px" });
    expect(JSON.parse(window.sessionStorage.getItem("agent-position") ?? "null")).toEqual({
      x: 240,
      y: 180,
    });
  });

  it("uses the close button without starting a drag", () => {
    const onClose = vi.fn();
    render(
      <DraggableModal isOpen onClose={onClose} title="閉じる操作">
        content
      </DraggableModal>
    );

    fireEvent.mouseDown(screen.getByRole("button", { name: "AIエージェントを閉じる" }), {
      clientX: 300,
      clientY: 200,
    });
    fireEvent.click(screen.getByRole("button", { name: "AIエージェントを閉じる" }));

    expect(onClose).toHaveBeenCalledOnce();
    expect(screen.getByRole("dialog")).toHaveStyle({ cursor: "auto" });
  });
});
