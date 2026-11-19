// 回答までのステップの構造化データ描画が、旧形式の HTML を本文の描画に通した結果と同じ DOM になること、
// 更新で利用者の開閉や favicon の失敗表示が巻き戻らないことを検証する。
// Verifies that the structured steps-to-the-answer renderer produces the same DOM as the legacy HTML drawn
// through the prose renderer, and that an update never undoes the user's open state or a favicon failure.

import { fireEvent, render } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { beforeAll, describe, expect, it } from "vitest";

import { AnswerTrace } from "../components/chat_page/answer_trace";
import { BotMessageHtml } from "../components/chat_page/bot_message_html";
import { normalizeAnswerTrace } from "../lib/chat_page/answer_trace";
import type { AnswerTraceV1 } from "../lib/chat_page/types";

// 見本は旧 HTML と構造化データを同じ内容で対にしたもの（サーバー側のテストと共有）。
// The fixtures pair the legacy HTML with the structured data holding the same content (shared with the server tests).
const FIXTURE_DIR = "../tests/fixtures/answer_trace";
const FIXTURE_NAMES = ["full", "fallback_sources", "references_only", "escaped_markup"] as const;

function readFixture(name: (typeof FIXTURE_NAMES)[number]) {
  const html = readFileSync(`${FIXTURE_DIR}/${name}_legacy.html`, "utf8");
  const trace = normalizeAnswerTrace(JSON.parse(readFileSync(`${FIXTURE_DIR}/${name}.json`, "utf8")));
  if (!trace) throw new Error(`fixture ${name} did not normalize`);
  return { html, trace };
}

// DOM を比べられる文字列にする。タグ・属性（名前順）・テキストは厳密に比べる。
// 吸収する差は 1 つだけ: 空白だけのテキストノード（旧 HTML の要素間にある改行）を無視し、隣り合うテキストノードは 1 つとして扱う。
// これは表示に影響しない。要素どうしは inline/flex 配置で、要素間の改行は描画されないため。
// Turn a DOM into a comparable string. Tags, attributes (sorted by name) and text are compared strictly.
// The only difference absorbed is whitespace-only text nodes (the newlines between elements in the legacy HTML),
// which are ignored; adjacent text nodes count as one. This does not affect rendering: the elements are laid out
// as flex/inline boxes where a newline between them is not painted.
function canonicalize(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) return JSON.stringify(node.textContent);
  const element = node as Element;
  const attributes = Array.from(element.attributes)
    .map((attribute) => `${attribute.name}=${JSON.stringify(attribute.value)}`)
    .sort()
    .join(" ");
  const children: string[] = [];
  let pendingText = "";
  const flushText = () => {
    if (pendingText.trim()) children.push(JSON.stringify(pendingText));
    pendingText = "";
  };
  element.childNodes.forEach((child) => {
    if (child.nodeType === Node.TEXT_NODE) {
      pendingText += child.textContent ?? "";
      return;
    }
    flushText();
    children.push(canonicalize(child));
  });
  flushText();
  return `<${element.tagName.toLowerCase()} ${attributes}>${children.join("")}</${element.tagName.toLowerCase()}>`;
}

beforeAll(() => {
  // jsdom には scrollIntoView が無いため、開閉後の表示位置調整を無効化する。
  // jsdom has no scrollIntoView, so the post-toggle reveal is stubbed out.
  if (typeof Element.prototype.scrollIntoView !== "function") {
    Element.prototype.scrollIntoView = () => {};
  }
});

describe("AnswerTrace DOM parity with the legacy HTML", () => {
  it.each(FIXTURE_NAMES)("renders the same DOM as the legacy HTML for the %s fixture", (name) => {
    const { html, trace } = readFixture(name);
    const legacy = render(<BotMessageHtml text={html} />);
    const legacyDom = canonicalize(legacy.container);
    legacy.unmount();

    const structured = render(<AnswerTrace trace={trace} />);

    // 比較が空振りしていないことの確認: 見出しとステップが実際に描かれている
    // Guard against a vacuous comparison: the heading and the steps are really drawn
    expect(structured.container.querySelector(".web-search-sources__label")).toHaveTextContent("回答までのステップ");
    expect(structured.container.querySelectorAll(".web-search-sources__step").length).toBe(trace.steps.length);
    expect(canonicalize(structured.container)).toBe(legacyDom);
  });

  it("matches the legacy markup for every kind of source, including a followed page and a title that is its URL", () => {
    const { trace } = readFixture("full");
    const { container } = render(<AnswerTrace trace={trace} />);

    const followed = container.querySelector(".web-search-sources__item--followed .web-search-sources__depth");
    expect(followed).toHaveTextContent("example.com から2階層先");
    expect(container.querySelector('a[href="https://travel.example.org/plan"] .web-search-sources__title')).toHaveTextContent(
      "https://travel.example.org/plan",
    );
    const link = container.querySelector<HTMLAnchorElement>(".web-search-sources__link");
    expect(link?.getAttribute("rel")).toBe("noopener noreferrer");
    expect(link?.getAttribute("target")).toBe("_blank");
  });
});

function traceWithStatus(status: "running" | "done" | "failed"): AnswerTraceV1 {
  return {
    version: 1,
    summary: "",
    steps: [
      {
        id: "s1",
        kind: "search",
        status,
        title: "Web検索",
        detail: "",
        query: "",
        badge: "",
        chips: [],
        sources: [],
      },
    ],
  };
}

describe("AnswerTrace running state", () => {
  it("adds one class to a running step and leaves the rest of its DOM as it is for a done step", () => {
    const running = render(<AnswerTrace trace={traceWithStatus("running")} />);
    const runningStep = running.container.querySelector(".web-search-sources__step");
    expect(runningStep).toHaveClass("web-search-sources__step--running");
    const runningDom = canonicalize(running.container).replace(" web-search-sources__step--running", "");
    running.unmount();

    const done = render(<AnswerTrace trace={traceWithStatus("done")} />);
    expect(done.container.querySelector(".web-search-sources__step")).not.toHaveClass("web-search-sources__step--running");
    expect(canonicalize(done.container)).toBe(runningDom);
  });

  it("does not add a class for a failed step; its kind decides the look", () => {
    const { container } = render(<AnswerTrace trace={traceWithStatus("failed")} />);
    expect(container.querySelector(".web-search-sources__step")?.className).toBe(
      "web-search-sources__step web-search-sources__step--search",
    );
  });
});

describe("AnswerTrace updates", () => {
  function sourceStep(status: "running" | "done") {
    return {
      id: "s1",
      kind: "search" as const,
      status,
      title: "Web検索",
      detail: "",
      query: "",
      badge: "",
      chips: [],
      sources: [
        {
          url: "https://example.com/a",
          title: "A",
          hostname: "example.com",
          favicon_url: "https://example.com/favicon.ico",
          fallback_label: "E",
          link_depth: 0,
          linked_from: "",
        },
      ],
    };
  }

  it("keeps what the user opened and a failed favicon when steps are added or change state", () => {
    const first: AnswerTraceV1 = { version: 1, summary: "", steps: [sourceStep("running")] };
    const { container, rerender } = render(<AnswerTrace trace={first} />);

    const rootDetails = container.querySelector<HTMLDetailsElement>("details.web-search-sources--trace");
    const stepDetails = container.querySelector<HTMLDetailsElement>("details.web-search-sources__step-details");
    const icon = container.querySelector(".web-search-citation__icon");
    // 利用者が開いた状態と、favicon の読み込み失敗（ハンドラが頭文字表示のクラスを足す）を作る。
    // Make the user's open state and a favicon failure (the handler adds the initial-letter class).
    rootDetails!.open = true;
    stepDetails!.open = true;
    fireEvent.error(container.querySelector("img.web-search-citation__favicon")!);
    expect(icon).toHaveClass("web-search-citation__icon--fallback");

    const second: AnswerTraceV1 = {
      version: 1,
      summary: "Web検索1回",
      steps: [
        sourceStep("done"),
        { ...sourceStep("done"), id: "s2", kind: "answer", title: "回答を作成", sources: [] },
      ],
    };
    rerender(<AnswerTrace trace={second} />);

    expect(container.querySelector("details.web-search-sources--trace")).toBe(rootDetails);
    expect(container.querySelector("details.web-search-sources__step-details")).toBe(stepDetails);
    expect(rootDetails!.open).toBe(true);
    expect(stepDetails!.open).toBe(true);
    expect(container.querySelector(".web-search-citation__icon")).toBe(icon);
    expect(icon).toHaveClass("web-search-citation__icon--fallback");
    expect(container.querySelector(".web-search-sources__step--running")).toBeNull();
    expect(container.querySelectorAll(".web-search-sources__step").length).toBe(2);
    expect(container.querySelector(".web-search-sources__count")).toHaveTextContent("2ステップ");
    expect(container.querySelector(".web-search-sources__summary-detail")).toHaveTextContent("Web検索1回");
  });

  it("opens and closes the panel through the shared source interactions", () => {
    const { trace } = readFixture("references_only");
    const { container } = render(<AnswerTrace trace={trace} />);
    const rootDetails = container.querySelector<HTMLDetailsElement>("details.web-search-sources--trace")!;

    fireEvent.click(container.querySelector(".web-search-sources__summary")!);
    expect(rootDetails.open).toBe(true);
    fireEvent.click(container.querySelector(".web-search-sources__summary")!);
    expect(rootDetails.open).toBe(false);
  });
});
