import { describe, expect, it } from "vitest";

import { applyStreamingWordReveal } from "../lib/chat_page/streaming_word_dom";
import {
  WORD_REVEAL_DURATION_MS,
  WORD_REVEAL_STAGGER_MS,
  WordRevealTimeline,
} from "../lib/chat_page/streaming_word_reveal";

function renderContainer(html: string) {
  const container = document.createElement("div");
  container.innerHTML = html;
  document.body.appendChild(container);
  return container;
}

function revealedWords(container: HTMLElement) {
  return Array.from(container.querySelectorAll("span.streaming-word")).map(
    (span) => span.textContent ?? "",
  );
}

describe("applyStreamingWordReveal", () => {
  it("wraps each newly revealed word without changing the rendered text", () => {
    const container = renderContainer("<p>Hello brave world</p>");
    const timeline = new WordRevealTimeline();

    applyStreamingWordReveal(container, timeline, 1000);

    expect(revealedWords(container)).toEqual(["Hello", "brave", "world"]);
    expect(container.textContent).toBe("Hello brave world");
  });

  it("splits Japanese text into per-character words", () => {
    const container = renderContainer("<p>こんにちは</p>");

    applyStreamingWordReveal(container, new WordRevealTimeline(), 1000);

    expect(revealedWords(container)).toEqual(["こ", "ん", "に", "ち", "は"]);
  });

  it("staggers the start of words that appear in the same frame", () => {
    const container = renderContainer("<p>Hello brave world</p>");

    applyStreamingWordReveal(container, new WordRevealTimeline(), 1000);

    const delays = Array.from(container.querySelectorAll<HTMLElement>("span.streaming-word")).map(
      (span) => span.style.animationDelay,
    );
    // 正のdelayは開始待ちを意味し、語が左から順に立ち上がるカスケードになる。
    // Positive delays mean "not started yet": the words cascade left to right.
    expect(delays).toEqual(["0ms", `${WORD_REVEAL_STAGGER_MS}ms`, `${WORD_REVEAL_STAGGER_MS * 2}ms`]);
  });

  it("resumes the animation with a negative delay instead of restarting it", () => {
    const timeline = new WordRevealTimeline();
    const first = renderContainer("<p>Hello world</p>");
    applyStreamingWordReveal(first, timeline, 1000);

    // ストリーミング中はHTMLごと再描画されるため、同じ内容を描き直して再適用する。
    // Streaming re-renders the whole HTML, so redraw the same content and reapply.
    const second = renderContainer("<p>Hello world</p>");
    applyStreamingWordReveal(second, timeline, 1120);

    const delays = Array.from(second.querySelectorAll<HTMLElement>("span.streaming-word")).map(
      (span) => span.style.animationDelay,
    );
    expect(delays).toEqual(["-120ms", `${WORD_REVEAL_STAGGER_MS - 120}ms`]);
  });

  it("does not replay visible words when markdown finalizes mid-stream", () => {
    const timeline = new WordRevealTimeline();
    const first = renderContainer("<p>Streaming **bold</p>");
    applyStreamingWordReveal(first, timeline, 1000);

    // `**` が <strong> へ確定し、描画テキストが途中から差し替わるフレーム。
    // The frame where `**` collapses into <strong> and the text shifts.
    const second = renderContainer("<p>Streaming <strong>bold</strong></p>");
    applyStreamingWordReveal(second, timeline, 1000 + WORD_REVEAL_DURATION_MS + WORD_REVEAL_STAGGER_MS);

    // 再生し終えていた "Streaming" は透明に戻らず、素のテキストのまま残る。
    // "Streaming" already finished playing and must not fade in again.
    const words = revealedWords(second);
    expect(words).not.toContain("Streaming");
    expect(second.textContent).toBe("Streaming bold");
  });

  it("stops wrapping a word once its animation finished", () => {
    const timeline = new WordRevealTimeline();
    const first = renderContainer("<p>Hello world</p>");
    applyStreamingWordReveal(first, timeline, 1000);

    const second = renderContainer("<p>Hello world</p>");
    applyStreamingWordReveal(second, timeline, 1000 + WORD_REVEAL_DURATION_MS + WORD_REVEAL_STAGGER_MS);

    expect(revealedWords(second)).toEqual([]);
    expect(second.textContent).toBe("Hello world");
  });

  it("exposes the animation duration to CSS", () => {
    const container = renderContainer("<p>Hello</p>");

    applyStreamingWordReveal(container, new WordRevealTimeline(), 1000);

    expect(container.style.getPropertyValue("--streaming-word-duration")).toBe(
      `${WORD_REVEAL_DURATION_MS}ms`,
    );
  });

  it("leaves code blocks and tables untouched", () => {
    const container = renderContainer(
      "<pre><code>const value = 1;</code></pre><table><tbody><tr><td>cell value</td></tr></tbody></table>",
    );

    applyStreamingWordReveal(container, new WordRevealTimeline(), 1000);

    expect(container.querySelector("pre span.streaming-word")).toBeNull();
    expect(container.querySelector("table span.streaming-word")).toBeNull();
  });

  it("only animates the tail of a long response", () => {
    const head = "old ".repeat(200);
    const container = renderContainer(`<p>${head}fresh tail</p>`);

    applyStreamingWordReveal(container, new WordRevealTimeline(), 1000);

    const words = revealedWords(container);
    expect(words.length).toBeLessThan(120);
    expect(words.slice(-2)).toEqual(["fresh", "tail"]);
  });

  it("keeps inline markup intact while animating its text", () => {
    const container = renderContainer("<p>See <strong>bold text</strong> here</p>");

    applyStreamingWordReveal(container, new WordRevealTimeline(), 1000);

    expect(container.querySelector("strong")?.textContent).toBe("bold text");
    expect(container.querySelectorAll("strong span.streaming-word")).toHaveLength(2);
    expect(container.textContent).toBe("See bold text here");
  });
});
