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
  it("wraps each newly revealed chunk without changing the rendered text", () => {
    const container = renderContainer("<p>Hello brave world</p>");
    const timeline = new WordRevealTimeline();

    applyStreamingWordReveal(container, timeline, 1000);

    // 1語ずつではなく、数語をまとめたかたまりが1回のフェード単位になる。
    // A few words at a time form one fade unit instead of one word each.
    expect(revealedWords(container)).toEqual(["Hello brave", "world"]);
    expect(container.textContent).toBe("Hello brave world");
  });

  it("groups Japanese text into chunks that break at punctuation", () => {
    const container = renderContainer("<p>こんにちは、今日はいい天気ですね</p>");

    applyStreamingWordReveal(container, new WordRevealTimeline(), 1000);

    // 1文字ずつだと生成が速いときタイプライターに見えるため、読点までや刻み幅
    // ぶんをひとかたまりにする。
    // One character at a time reads as a typewriter when generation is fast, so
    // the text up to the comma — or up to the step grid — becomes one chunk.
    expect(revealedWords(container)).toEqual(["こんにちは、", "今日はい", "い天気ですね"]);
  });

  it("staggers the start of chunks that appear in the same frame", () => {
    const container = renderContainer("<p>Hello brave world</p>");

    applyStreamingWordReveal(container, new WordRevealTimeline(), 1000);

    const delays = Array.from(container.querySelectorAll<HTMLElement>("span.streaming-word")).map(
      (span) => span.style.animationDelay,
    );
    // 正のdelayは開始待ちを意味し、かたまりが左から順に立ち上がるカスケードになる。
    // Positive delays mean "not started yet": the chunks cascade left to right.
    expect(delays).toEqual(["0ms", `${WORD_REVEAL_STAGGER_MS}ms`]);
  });

  it("resumes the animation with a negative delay instead of restarting it", () => {
    const timeline = new WordRevealTimeline();
    const first = renderContainer("<p>Hello brave world</p>");
    applyStreamingWordReveal(first, timeline, 1000);

    // ストリーミング中はHTMLごと再描画されるため、同じ内容を描き直して再適用する。
    // Streaming re-renders the whole HTML, so redraw the same content and reapply.
    const second = renderContainer("<p>Hello brave world</p>");
    applyStreamingWordReveal(second, timeline, 1120);

    const delays = Array.from(second.querySelectorAll<HTMLElement>("span.streaming-word")).map(
      (span) => span.style.animationDelay,
    );
    expect(delays).toEqual(["-120ms", `${WORD_REVEAL_STAGGER_MS - 120}ms`]);
  });

  it("fades in only the newly appended part of a chunk that keeps growing", () => {
    const timeline = new WordRevealTimeline();
    const first = renderContainer("<p>これは</p>");
    applyStreamingWordReveal(first, timeline, 1000);

    // 同じチャンクに文字が足されたフレーム。表示済みの「これは」は巻き戻さず、
    // 追記された「テスト」だけが新しくフェードインする。
    // A frame where the same chunk grew: the visible part must not rewind and
    // only the appended part starts a new fade.
    const second = renderContainer("<p>これはテスト</p>");
    applyStreamingWordReveal(second, timeline, 1100);

    expect(revealedWords(second)).toEqual(["これは", "テスト"]);
    const delays = Array.from(second.querySelectorAll<HTMLElement>("span.streaming-word")).map(
      (span) => span.style.animationDelay,
    );
    expect(delays).toEqual(["-100ms", "0ms"]);
  });

  it("keeps fading in new text when the markup ends with a newline node", () => {
    const timeline = new WordRevealTimeline();
    // Markdownの描画は本文の後ろに改行のテキストノードを残す。そのため追記しても
    // テキスト全体は「純粋な追記」に見えず、以前はこのフレームで新しい文字が
    // フェードインしなくなっていた（生成中ほぼ全フレームが該当する）。
    // Markdown rendering leaves a newline text node after the body, so an
    // append does not look like a pure append and new characters used to skip
    // their fade — which was nearly every frame of a streaming reply.
    const first = renderContainer("<p>これは</p>\n");
    applyStreamingWordReveal(first, timeline, 1000);

    const second = renderContainer("<p>これはテスト</p>\n");
    applyStreamingWordReveal(second, timeline, 1100);

    expect(revealedWords(second)).toEqual(["これは", "テスト"]);
    const delays = Array.from(second.querySelectorAll<HTMLElement>("span.streaming-word")).map(
      (span) => span.style.animationDelay,
    );
    expect(delays).toEqual(["-100ms", "0ms"]);
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

  it("only animates the newly appended tail of a long response", () => {
    const timeline = new WordRevealTimeline();
    const head = "old ".repeat(200);
    const first = renderContainer(`<p>${head.trim()}</p>`);
    applyStreamingWordReveal(first, timeline, 1000);

    const second = renderContainer(`<p>${head}fresh tail</p>`);
    applyStreamingWordReveal(second, timeline, 1050);

    // 末尾の追記ぶんだけがアニメーションし、既に描画済みの本文には触れない。
    // Only the appended tail animates; the body already on screen is untouched.
    expect(revealedWords(second)).toEqual([" fresh", "tail"]);
  });

  it("shows a bulk first render instantly instead of fading it afterwards", () => {
    // パーツ更新や復元では大量のテキストが一括で届く。後追いフェードさせない。
    // Parts updates / restores land lots of text at once; no after-the-fact fade.
    const container = renderContainer(`<p>${"word ".repeat(120)}</p>`);

    applyStreamingWordReveal(container, new WordRevealTimeline(), 1000);

    expect(revealedWords(container)).toEqual([]);
  });

  it("never turns previously rendered words transparent when the text reflows", () => {
    const timeline = new WordRevealTimeline();
    const first = renderContainer("<p>alpha beta gamma delta epsilon</p>");
    applyStreamingWordReveal(first, timeline, 1000);

    // 先頭がコードブロックへ確定し、アニメ対象テキストが途中から差し替わるフレーム。
    // The frame where the head finalizes into a code block and the animatable
    // text shifts mid-way.
    const second = renderContainer("<pre>alpha beta</pre><p>gamma delta epsilon zeta</p>");
    applyStreamingWordReveal(second, timeline, 1050);

    // 表示済みの語が開始待ち（正のdelay=透明）へ戻ることはない。
    // No already-rendered word may return to a queued (transparent) state.
    const delays = Array.from(second.querySelectorAll<HTMLElement>("span.streaming-word")).map(
      (span) => Number.parseInt(span.style.animationDelay, 10),
    );
    expect(delays.every((delay) => delay <= 0)).toBe(true);
    expect(second.textContent).toBe("alpha betagamma delta epsilon zeta");
  });

  it("keeps inline markup intact while animating its text", () => {
    const container = renderContainer("<p>See <strong>bold text</strong> here</p>");

    applyStreamingWordReveal(container, new WordRevealTimeline(), 1000);

    expect(container.querySelector("strong")?.textContent).toBe("bold text");
    // チャンクはテキストノードをまたがないので、<strong> の中身が1単位になる。
    // A chunk never spans text nodes, so the <strong> body is one unit.
    expect(container.querySelectorAll("strong span.streaming-word")).toHaveLength(1);
    expect(container.textContent).toBe("See bold text here");
  });
});
