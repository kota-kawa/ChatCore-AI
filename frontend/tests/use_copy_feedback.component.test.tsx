import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { COPY_FEEDBACK_RESET_MS, useCopyFeedback } from "../hooks/use_copy_feedback";

describe("useCopyFeedback", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("copies text, exposes the copied state, and reverts after the shared delay", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });

    const { result } = renderHook(() => useCopyFeedback());

    await act(async () => {
      await result.current.copy("hello");
    });

    expect(writeText).toHaveBeenCalledWith("hello");
    expect(result.current.copied).toBe(true);
    expect(result.current.state).toBe("copied");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(COPY_FEEDBACK_RESET_MS);
    });

    expect(result.current.copied).toBe(false);
    expect(result.current.state).toBe("idle");
  });

  it("ignores a second copy while the feedback is still showing", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });

    const { result } = renderHook(() => useCopyFeedback());

    await act(async () => {
      await Promise.all([result.current.copy("one"), result.current.copy("two")]);
    });

    expect(writeText).toHaveBeenCalledTimes(1);
    expect(writeText).toHaveBeenCalledWith("one");
  });

  it("run executes an arbitrary copy routine and flips the icon from its result", async () => {
    const { result } = renderHook(() => useCopyFeedback());

    const okTask = vi.fn().mockResolvedValue(true);
    await act(async () => {
      const ok = await result.current.run(okTask);
      expect(ok).toBe(true);
    });
    expect(result.current.copied).toBe(true);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(COPY_FEEDBACK_RESET_MS);
    });

    const failTask = vi.fn().mockResolvedValue(false);
    await act(async () => {
      await result.current.run(failTask);
    });
    expect(result.current.failed).toBe(true);
  });

  it("run ignores a re-entrant call while feedback is showing", async () => {
    const { result } = renderHook(() => useCopyFeedback());
    const task = vi.fn().mockResolvedValue(true);

    await act(async () => {
      await Promise.all([result.current.run(task), result.current.run(task)]);
    });

    expect(task).toHaveBeenCalledTimes(1);
  });

  it("markResult drives the icon state from an external copy routine", async () => {
    const { result } = renderHook(() => useCopyFeedback());

    act(() => {
      result.current.markResult(true);
    });
    expect(result.current.copied).toBe(true);

    act(() => {
      result.current.markResult(false);
    });
    expect(result.current.failed).toBe(true);
    expect(result.current.copied).toBe(false);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(COPY_FEEDBACK_RESET_MS);
    });
    expect(result.current.state).toBe("idle");
  });

  it("reports failure when the clipboard write throws", async () => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) },
    });
    Object.defineProperty(document, "execCommand", { configurable: true, value: vi.fn(() => false) });

    const { result } = renderHook(() => useCopyFeedback());

    let ok = true;
    await act(async () => {
      ok = await result.current.copy("nope");
    });

    expect(ok).toBe(false);
    expect(result.current.failed).toBe(true);
  });
});
