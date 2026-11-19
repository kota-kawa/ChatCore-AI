// 生成中の本文の描き直しが、重いときだけ間引かれ、完了時には必ず最新の本文になることを検証する。
// Tests that streaming re-renders are spaced out only when heavy, and that the final text always lands at completion.

import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// 描き直しにかかる時間を決められるよう、時計と Markdown 変換の所要時間を差し替える。
// The clock and the cost of the Markdown conversion are replaced so a render's duration can be chosen.
const clock = vi.hoisted(() => ({ now: 1000, renderCostMs: 0 }));

vi.mock("../scripts/chat/chat_ui", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../scripts/chat/chat_ui")>();
  return {
    ...actual,
    formatLLMOutput: vi.fn((text: string) => {
      clock.now += clock.renderCostMs;
      return actual.formatLLMOutput(text);
    }),
  };
});

import { BotMessageHtml } from "../components/chat_page/bot_message_html";
import { MAX_STREAM_RENDER_GAP_MS } from "../lib/chat_page/streaming_render_pace";
import { formatLLMOutput } from "../scripts/chat/chat_ui";

const HEAVY_RENDER_COST_MS = 40;

// 描かれている本文。Markdown 変換が段落の後ろに付ける改行は除く。
// The text currently drawn, without the newline the Markdown conversion puts after a paragraph.
function drawnText(container: HTMLElement) {
  return (container.textContent ?? "").trim();
}

function advance(ms: number) {
  act(() => {
    clock.now += ms;
    vi.advanceTimersByTime(ms);
  });
}

describe("BotMessageHtml streaming render pacing", () => {
  beforeEach(() => {
    clock.now = 1000;
    clock.renderCostMs = 0;
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    vi.spyOn(performance, "now").mockImplementation(() => clock.now);
    vi.mocked(formatLLMOutput).mockClear();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("re-renders on every change while renders are cheap", () => {
    clock.renderCostMs = 2;
    const { container, rerender } = render(<BotMessageHtml text="あ" streaming />);

    rerender(<BotMessageHtml text="あい" streaming />);
    expect(container).toHaveTextContent("あい");
    rerender(<BotMessageHtml text="あいう" streaming />);
    expect(container).toHaveTextContent("あいう");

    expect(formatLLMOutput).toHaveBeenCalledTimes(3);
  });

  it("spaces out heavy renders and then draws the latest text", () => {
    clock.renderCostMs = HEAVY_RENDER_COST_MS;
    const { container, rerender } = render(<BotMessageHtml text="あ" streaming />);
    expect(container).toHaveTextContent("あ");

    rerender(<BotMessageHtml text="あい" streaming />);
    rerender(<BotMessageHtml text="あいう" streaming />);
    expect(drawnText(container)).toBe("あ");

    advance(HEAVY_RENDER_COST_MS - 1);
    expect(drawnText(container)).toBe("あ");

    advance(1);
    expect(drawnText(container)).toBe("あいう");
    // 間の「あい」は描かれない。
    // The intermediate text is never rendered.
    expect(formatLLMOutput).toHaveBeenCalledTimes(2);
  });

  it("keeps spacing out the renders that follow a deferred one", () => {
    clock.renderCostMs = HEAVY_RENDER_COST_MS;
    const { container, rerender } = render(<BotMessageHtml text="あ" streaming />);
    rerender(<BotMessageHtml text="あい" streaming />);
    advance(HEAVY_RENDER_COST_MS);
    expect(drawnText(container)).toBe("あい");

    // 予約した描き直しも重かったので、その直後の更新はまた待たされる。
    // The deferred render was heavy too, so the update right after it waits again.
    rerender(<BotMessageHtml text="あいう" streaming />);
    expect(drawnText(container)).toBe("あい");

    advance(HEAVY_RENDER_COST_MS);
    expect(drawnText(container)).toBe("あいう");
    expect(formatLLMOutput).toHaveBeenCalledTimes(3);
  });

  it("fades in the words drawn by a deferred render", () => {
    clock.renderCostMs = HEAVY_RENDER_COST_MS;
    const { container, rerender } = render(<BotMessageHtml text="最初の文です。" streaming />);
    rerender(<BotMessageHtml text="最初の文です。遅れて描かれる続きの文です。" streaming />);

    advance(HEAVY_RENDER_COST_MS);

    const fadingText = Array.from(container.querySelectorAll("span.streaming-word"))
      .map((word) => word.textContent)
      .join("");
    expect(fadingText).toContain("続きの文");
  });

  it("does not hold text back longer than the cap, however heavy a render was", () => {
    clock.renderCostMs = MAX_STREAM_RENDER_GAP_MS * 4;
    const { container, rerender } = render(<BotMessageHtml text="あ" streaming />);

    rerender(<BotMessageHtml text="あい" streaming />);
    expect(drawnText(container)).toBe("あ");

    advance(MAX_STREAM_RENDER_GAP_MS);
    expect(drawnText(container)).toBe("あい");
  });

  it("draws the final text at once when streaming ends and leaves no deferred render behind", () => {
    clock.renderCostMs = HEAVY_RENDER_COST_MS;
    const { container, rerender } = render(<BotMessageHtml text="あ" streaming />);
    rerender(<BotMessageHtml text="あい" streaming />);
    expect(drawnText(container)).toBe("あ");

    rerender(<BotMessageHtml text="あいう" />);
    expect(drawnText(container)).toBe("あいう");
    expect(container.querySelector("span.streaming-word")).toBeNull();
    expect(formatLLMOutput).toHaveBeenCalledTimes(2);

    advance(MAX_STREAM_RENDER_GAP_MS * 2);
    expect(drawnText(container)).toBe("あいう");
    expect(formatLLMOutput).toHaveBeenCalledTimes(2);
  });

  it("does not render after unmount", () => {
    clock.renderCostMs = HEAVY_RENDER_COST_MS;
    const { rerender, unmount } = render(<BotMessageHtml text="あ" streaming />);
    rerender(<BotMessageHtml text="あい" streaming />);

    unmount();
    advance(MAX_STREAM_RENDER_GAP_MS * 2);

    expect(formatLLMOutput).toHaveBeenCalledTimes(1);
  });
});
