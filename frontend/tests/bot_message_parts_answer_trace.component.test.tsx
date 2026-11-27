// 回答までのステップ（実行記録）のパーツが、直後の本文と同じ枠の中に描かれること、
// 生成中に記録や本文が後から加わっても、先に描かれていた側を作り直さないことを検証する。
// Verifies that the steps-to-the-answer (execution record) part is drawn inside the wrapper of the prose that
// follows it, and that when the record or the prose joins later during generation, whichever was drawn first is
// not remounted.

import { fireEvent, render } from "@testing-library/react";
import { beforeAll, describe, expect, it } from "vitest";

import { BotMessageParts } from "../components/chat_page/bot_message_parts";
import { SharedChatMessageParts } from "../components/shared_chat/shared_chat_message_parts";
import type { ChatMessagePart } from "../lib/chat_page/types";
import { makeStep, makeTrace } from "./answer_trace_test_data";

const TRACE_PART: ChatMessagePart = { type: "answer_trace", trace: makeTrace([makeStep({ title: "Web検索" })]) };
const LEGACY_TRACE_PART: ChatMessagePart = {
  type: "legacy_answer_trace",
  html: '<details class="web-search-sources web-search-sources--trace"><summary class="web-search-sources__summary">回答までのステップ</summary></details>',
};
const TEXT_PART: ChatMessagePart = { type: "text", text: "本文です。" };
const IMAGE_PART: ChatMessagePart = {
  type: "web_search_image",
  image: { url: "https://cdn.example.com/hero.jpg", alt: "写真", sourceUrl: "https://example.com/article" },
};

const TRACE_SELECTOR = "details.web-search-sources--trace";

beforeAll(() => {
  if (typeof Element.prototype.scrollIntoView !== "function") {
    Element.prototype.scrollIntoView = () => {};
  }
});

function wrappers(container: HTMLElement) {
  return Array.from(container.querySelectorAll<HTMLElement>(".bot-message-part"));
}

describe.each([
  ["BotMessageParts", (parts: ChatMessagePart[]) => <BotMessageParts fallbackText="" parts={parts} />],
  ["SharedChatMessageParts", (parts: ChatMessagePart[]) => <SharedChatMessageParts fallbackText="" parts={parts} />],
])("%s with an execution record", (_name, renderParts) => {
  // 記録の下の余白と本文の上の余白が相殺されるのは、同じ枠の中で隣り合うときだけ。
  // The record's bottom margin and the prose's top margin only collapse when they are neighbours in one wrapper.
  it.each([
    ["structured", TRACE_PART],
    ["saved before structuring", LEGACY_TRACE_PART],
  ])("draws a %s record inside the wrapper of the prose that follows it", (_kind, tracePart) => {
    const { container } = render(renderParts([tracePart, TEXT_PART]));

    const [wrapper, ...rest] = wrappers(container);
    expect(rest).toHaveLength(0);
    expect(wrapper).toHaveClass("bot-message-part--text");
    const trace = wrapper.querySelector(TRACE_SELECTOR);
    const prose = wrapper.querySelector("p");
    expect(trace).not.toBeNull();
    expect(prose).toHaveTextContent("本文です。");
    expect(trace!.compareDocumentPosition(prose!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("gives the record a wrapper of its own when something other than prose follows", () => {
    const { container } = render(renderParts([TRACE_PART, IMAGE_PART, TEXT_PART]));

    const [traceWrapper, imageWrapper, textWrapper] = wrappers(container);
    expect(traceWrapper).toHaveClass("bot-message-part--answer-trace");
    expect(traceWrapper.querySelector(TRACE_SELECTOR)).not.toBeNull();
    expect(imageWrapper).toHaveClass("bot-message-part--web-search-image");
    expect(textWrapper.querySelector(TRACE_SELECTOR)).toBeNull();
    expect(textWrapper).toHaveTextContent("本文です。");
  });

  it("draws a record that has no prose yet", () => {
    const { container } = render(renderParts([TRACE_PART]));

    expect(wrappers(container)).toHaveLength(1);
    expect(container.querySelector(TRACE_SELECTOR)).not.toBeNull();
  });
});

describe("BotMessageParts while an answer is generated", () => {
  it("keeps the prose being drawn when the record joins ahead of it", () => {
    const { container, rerender } = render(<BotMessageParts fallbackText="" parts={[TEXT_PART]} streaming />);
    const proseContainer = container.querySelector("p")!.parentElement;

    rerender(<BotMessageParts fallbackText="" parts={[TRACE_PART, TEXT_PART]} streaming />);

    expect(container.querySelector(TRACE_SELECTOR)).not.toBeNull();
    expect(container.querySelector("p")!.parentElement).toBe(proseContainer);
  });

  it("expands the record until the streamed prose finishes", () => {
    const { container, rerender } = render(<BotMessageParts fallbackText="" parts={[TRACE_PART]} streaming />);
    const trace = container.querySelector<HTMLDetailsElement>(TRACE_SELECTOR)!;
    expect(trace.open).toBe(true);

    rerender(<BotMessageParts fallbackText="" parts={[TRACE_PART, TEXT_PART]} streaming />);

    expect(container.querySelector(TRACE_SELECTOR)).toBe(trace);
    expect(trace.open).toBe(true);
    expect(trace.closest(".bot-message-part")).toBe(container.querySelector("p")!.closest(".bot-message-part"));

    rerender(<BotMessageParts fallbackText="" parts={[TRACE_PART, TEXT_PART]} />);

    expect(container.querySelector(TRACE_SELECTOR)).toBe(trace);
    expect(trace.open).toBe(false);
  });

  it("honors manual toggles even when the record and the prose get separate wrappers", () => {
    const { container, rerender } = render(<BotMessageParts fallbackText="" parts={[TRACE_PART]} streaming />);
    const trace = container.querySelector<HTMLDetailsElement>(TRACE_SELECTOR)!;
    const summary = trace.querySelector("summary")!;
    fireEvent.click(summary);
    expect(trace.open).toBe(false);

    rerender(<BotMessageParts fallbackText="" parts={[TRACE_PART, IMAGE_PART, TEXT_PART]} streaming />);

    expect(container.querySelector(TRACE_SELECTOR)).toBe(trace);
    expect(trace.open).toBe(false);
    fireEvent.click(summary);
    expect(trace.open).toBe(true);

    rerender(<BotMessageParts fallbackText="" parts={[TRACE_PART, IMAGE_PART, TEXT_PART]} />);

    expect(trace.open).toBe(true);
  });
});
