import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DraggableModal } from "../components/ui/DraggableModal";

describe("DraggableModal", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => (
      window.setTimeout(() => callback(performance.now()), 16)
    ));
    vi.stubGlobal("cancelAnimationFrame", (frameId: number) => window.clearTimeout(frameId));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
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
    act(() => vi.advanceTimersByTime(32));
    act(() => vi.advanceTimersByTime(0));

    expect(screen.getByRole("dialog", { name: "テストモーダル" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "チャコを閉じる" })).toHaveFocus();

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

    const dialog = screen.getByRole("dialog", { hidden: true });
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
    act(() => vi.advanceTimersByTime(32));

    fireEvent.mouseDown(screen.getByRole("button", { name: "チャコを閉じる" }), {
      clientX: 300,
      clientY: 200,
    });
    fireEvent.click(screen.getByRole("button", { name: "チャコを閉じる" }));

    expect(onClose).toHaveBeenCalledOnce();
    expect(screen.getByRole("dialog")).toHaveStyle({ cursor: "auto" });
  });

  it("focuses an explicitly requested input when the dialog opens", () => {
    render(
      <DraggableModal
        isOpen
        onClose={vi.fn()}
        title="入力フォーカス"
        initialFocusSelector=".agent-input"
      >
        <textarea className="agent-input" aria-label="依頼内容" />
      </DraggableModal>
    );

    act(() => vi.advanceTimersByTime(32));
    act(() => vi.advanceTimersByTime(0));

    expect(screen.getByRole("textbox", { name: "依頼内容" })).toHaveFocus();
  });

  it("keeps focus away from text input on touch-sized viewports", () => {
    vi.spyOn(window, "innerWidth", "get").mockReturnValue(390);

    render(
      <DraggableModal
        isOpen
        onClose={vi.fn()}
        title="モバイル入力"
        initialFocusSelector=".agent-input"
        avoidTextInputFocusOnTouch
      >
        <textarea className="agent-input" aria-label="モバイル依頼内容" />
      </DraggableModal>
    );

    act(() => vi.advanceTimersByTime(32));
    act(() => vi.advanceTimersByTime(0));

    expect(screen.getByRole("button", { name: "チャコを閉じる" })).toHaveFocus();
    expect(screen.getByRole("textbox", { name: "モバイル依頼内容" })).not.toHaveFocus();
  });

  it("prepares the mounted surface before starting its entry animation", () => {
    const { rerender } = render(
      <DraggableModal isOpen={false} onClose={vi.fn()} title="表示準備">
        content
      </DraggableModal>
    );

    rerender(
      <DraggableModal isOpen onClose={vi.fn()} title="表示準備">
        content
      </DraggableModal>
    );

    const dialog = document.querySelector<HTMLElement>(".global-ai-agent-modal");
    expect(dialog).not.toBeNull();
    expect(dialog).toHaveClass("is-preparing");

    act(() => vi.advanceTimersByTime(32));

    expect(dialog).toHaveClass("is-open");
  });

  it("shrinks to the visual viewport and pulls itself above the on-screen keyboard", () => {
    // jsdom には visualViewport が無いので、キーボードで縮む表示領域を EventTarget で再現する
    // jsdom has no visualViewport, so stand in an EventTarget that shrinks like the real one
    const visualViewport = Object.assign(new EventTarget(), {
      offsetLeft: 0,
      offsetTop: 0,
      width: 390,
      height: 740,
    });
    vi.stubGlobal("visualViewport", visualViewport);
    vi.spyOn(window, "innerWidth", "get").mockReturnValue(390);
    vi.spyOn(window, "innerHeight", "get").mockReturnValue(740);

    render(
      <DraggableModal isOpen onClose={vi.fn()} title="キーボード回避" initialX={12} initialY={100}>
        <textarea aria-label="依頼内容" />
      </DraggableModal>
    );
    act(() => vi.advanceTimersByTime(32));

    const dialog = document.querySelector<HTMLElement>(".global-ai-agent-modal");
    expect(dialog?.style.getPropertyValue("--draggable-modal-viewport-height")).toBe("740px");
    expect(dialog).toHaveStyle({ top: "100px" });

    // キーボードが開く / The keyboard opens
    act(() => {
      visualViewport.height = 410;
      visualViewport.dispatchEvent(new Event("resize"));
      vi.advanceTimersByTime(32);
    });

    expect(dialog?.style.getPropertyValue("--draggable-modal-viewport-height")).toBe("410px");
    expect(dialog).toHaveStyle({ top: "12px" });

    // キーボードが閉じたら元の高さへ戻す / Restore the full height once the keyboard closes
    act(() => {
      visualViewport.height = 740;
      visualViewport.dispatchEvent(new Event("resize"));
      vi.advanceTimersByTime(32);
    });

    expect(dialog?.style.getPropertyValue("--draggable-modal-viewport-height")).toBe("740px");
  });

  it("moves an overlapping desktop position away from the launcher before entry", () => {
    vi.spyOn(window, "innerWidth", "get").mockReturnValue(1366);
    vi.spyOn(window, "innerHeight", "get").mockReturnValue(768);
    vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(392);
    vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(620);
    const launcher = document.createElement("button");
    launcher.className = "test-agent-launcher";
    launcher.getBoundingClientRect = () => ({
      left: 40,
      top: 668,
      right: 100,
      bottom: 728,
      width: 60,
      height: 60,
      x: 40,
      y: 668,
      toJSON: () => undefined,
    });
    document.body.append(launcher);

    render(
      <DraggableModal
        isOpen
        onClose={vi.fn()}
        title="重なり回避"
        initialX={20}
        initialY={100}
        avoidElementSelector=".test-agent-launcher"
        avoidElementMinViewportWidth={641}
      >
        content
      </DraggableModal>
    );

    expect(document.querySelector(".global-ai-agent-modal")).toHaveStyle({ left: "20px", top: "36px" });
    launcher.remove();
  });
});
