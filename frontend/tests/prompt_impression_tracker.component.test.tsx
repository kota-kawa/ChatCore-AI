import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { PromptRecord } from "../components/prompt_share/prompt_card";

const recordPromptImpressions = vi.fn((_ids: Array<string | number>) => Promise.resolve({ status: "success", counted: 1 }));

vi.mock("../scripts/prompt_share/api", () => ({
  recordPromptImpressions: (ids: Array<string | number>) => recordPromptImpressions(ids)
}));

import { usePromptImpressionTracker } from "../components/prompt_share/use_prompt_impression_tracker";

function prompt(id: number | undefined): PromptRecord {
  return {
    id,
    clientId: `prompt-${String(id)}`,
    title: "t",
    content: "c",
    liked: false,
    used_in_chat: false
  };
}

describe("usePromptImpressionTracker", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    recordPromptImpressions.mockClear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("batches the cards seen within the delay and sends each id once", () => {
    const { result } = renderHook(() => usePromptImpressionTracker());

    result.current(prompt(1));
    result.current(prompt(2));
    result.current(prompt(1));
    result.current(prompt(undefined));
    expect(recordPromptImpressions).not.toHaveBeenCalled();

    vi.advanceTimersByTime(1500);

    expect(recordPromptImpressions).toHaveBeenCalledTimes(1);
    expect(recordPromptImpressions).toHaveBeenCalledWith(["1", "2"]);
  });

  it("never sends an id that was already reported", () => {
    const { result } = renderHook(() => usePromptImpressionTracker());

    result.current(prompt(1));
    vi.advanceTimersByTime(1500);
    result.current(prompt(1));
    vi.advanceTimersByTime(1500);

    expect(recordPromptImpressions).toHaveBeenCalledTimes(1);
  });

  it("flushes what is pending when the page is hidden", () => {
    const { result } = renderHook(() => usePromptImpressionTracker());

    result.current(prompt(3));
    window.dispatchEvent(new Event("pagehide"));

    expect(recordPromptImpressions).toHaveBeenCalledWith(["3"]);
    vi.advanceTimersByTime(1500);
    expect(recordPromptImpressions).toHaveBeenCalledTimes(1);
  });
});
