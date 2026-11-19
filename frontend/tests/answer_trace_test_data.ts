// 回答までのステップのテストで使う構造化データの組み立て。
// Builders for the structured steps-to-the-answer data used by the tests.

import type { AnswerTraceSource, AnswerTraceStep, AnswerTraceV1 } from "../lib/chat_page/types";

export function makeSource(overrides: Partial<AnswerTraceSource> = {}): AnswerTraceSource {
  return {
    url: "https://example.com/a",
    title: "A",
    hostname: "example.com",
    favicon_url: "https://example.com/favicon.ico",
    fallback_label: "E",
    link_depth: 0,
    linked_from: "",
    ...overrides,
  };
}

export function makeStep(overrides: Partial<AnswerTraceStep> = {}): AnswerTraceStep {
  return {
    id: "s1",
    kind: "search",
    status: "done",
    title: "Web検索",
    detail: "",
    query: "",
    badge: "",
    chips: [],
    sources: [],
    ...overrides,
  };
}

export function makeTrace(steps: AnswerTraceStep[] = [makeStep()], summary = ""): AnswerTraceV1 {
  return { version: 1, summary, steps };
}
