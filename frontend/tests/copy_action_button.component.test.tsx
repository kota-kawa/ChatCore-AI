import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CopyActionButton } from "../components/chat_page/copy_action_button";

describe("CopyActionButton", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows success feedback, prevents duplicate copies, and resets", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    const getText = vi.fn(() => "copy me");
    render(<CopyActionButton getText={getText} />);

    const button = screen.getByRole("button", { name: "メッセージをコピー" });
    await act(async () => {
      fireEvent.click(button);
      fireEvent.click(button);
      await Promise.resolve();
    });

    expect(button).toHaveClass("copy-btn--success");
    expect(button).toBeDisabled();
    expect(button.querySelector("i")).toHaveClass("bi-check-lg");
    expect(writeText).toHaveBeenCalledOnce();
    expect(writeText).toHaveBeenCalledWith("copy me");
    expect(getText).toHaveBeenCalledOnce();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(button).toBeEnabled();
    expect(button).not.toHaveClass("copy-btn--success");
    expect(button.querySelector("i")).toHaveClass("bi-clipboard");
  });

  it("shows error feedback when both clipboard strategies fail", async () => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) },
    });
    Object.defineProperty(document, "execCommand", {
      configurable: true,
      value: vi.fn(() => false),
    });
    render(<CopyActionButton getText={() => "copy me"} />);

    const button = screen.getByRole("button", { name: "メッセージをコピー" });
    await act(async () => {
      fireEvent.click(button);
      await Promise.resolve();
    });

    expect(button).toHaveClass("copy-btn--error");
    expect(button.querySelector("i")).toHaveClass("bi-x-lg");
  });
});
