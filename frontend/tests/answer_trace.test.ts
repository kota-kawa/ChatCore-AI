// 回答までのステップの正規化・パーツ列への載せ方・表示順の規則を検証する。
// Tests normalization of the steps to the answer, how they sit in the part list, and the display order rules.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  isSameAnswerTrace,
  normalizeAnswerTrace,
  withAnswerTracePart,
} from "../lib/chat_page/answer_trace";
import { normalizeChatMessageParts } from "../lib/chat_page/api_contract";
import type { ChatMessagePart } from "../lib/chat_page/types";
import { makeSource, makeStep, makeTrace } from "./answer_trace_test_data";

const FIXTURE_DIR = "../tests/fixtures/answer_trace";

test("the server's structured fixtures pass through normalization unchanged", () => {
  for (const name of ["full", "fallback_sources", "references_only", "escaped_markup"]) {
    const raw = JSON.parse(readFileSync(`${FIXTURE_DIR}/${name}.json`, "utf8"));
    assert.deepEqual(normalizeAnswerTrace(raw), raw, name);
  }
});

test("a trace needs version 1 and at least one titled step", () => {
  assert.equal(normalizeAnswerTrace(null), null);
  assert.equal(normalizeAnswerTrace({ version: 2, summary: "", steps: [makeStep()] }), null);
  assert.equal(normalizeAnswerTrace({ version: 1, summary: "", steps: [] }), null);
  assert.equal(normalizeAnswerTrace({ version: 1, summary: "", steps: [{ ...makeStep(), title: "  " }, "x"] }), null);
});

test("unknown kind and status fall back to info and done", () => {
  const trace = normalizeAnswerTrace({ version: 1, steps: [{ ...makeStep(), kind: "mystery", status: "paused" }] });
  assert.equal(trace?.steps[0].kind, "info");
  assert.equal(trace?.steps[0].status, "done");
  assert.equal(trace?.summary, "");
});

test("text is whitespace-collapsed and truncated with an ellipsis at the contract limits", () => {
  const trace = normalizeAnswerTrace({
    version: 1,
    summary: "a\n b",
    steps: [{ ...makeStep(), title: "t".repeat(130), detail: "d".repeat(300), badge: "b".repeat(30), query: "q".repeat(130) }],
  });
  const step = trace!.steps[0];
  assert.equal(trace!.summary, "a b");
  assert.equal(step.title, `${"t".repeat(117)}...`);
  assert.equal(step.detail, `${"d".repeat(257)}...`);
  assert.equal(step.badge, `${"b".repeat(21)}...`);
  assert.equal(step.query, `${"q".repeat(117)}...`);
});

test("chips are trimmed of empties and capped at 8, sources at 40, steps at 60", () => {
  const chips = ["", ...Array.from({ length: 12 }, (_, index) => `c${index}`)];
  const sources = Array.from({ length: 45 }, (_, index) => makeSource({ url: `https://example.com/${index}` }));
  const steps = Array.from({ length: 65 }, (_, index) => makeStep({ id: `s${index + 1}`, chips, sources: index === 0 ? sources : [] }));
  const trace = normalizeAnswerTrace({ version: 1, summary: "", steps });
  assert.equal(trace!.steps.length, 60);
  assert.deepEqual(trace!.steps[0].chips, Array.from({ length: 8 }, (_, index) => `c${index}`));
  assert.equal(trace!.steps[0].sources.length, 40);
});

test("sources without a safe http(s) URL are dropped", () => {
  const bad = [
    "javascript:alert(1)",
    "data:text/html,<b>x</b>",
    "ftp://example.com/a",
    "https://user:pass@example.com/a",
    "https://@example.com/a",
    "https:///no-host",
    "/relative",
    "https://example.com/a\nb",
    `https://example.com/${"a".repeat(2100)}`,
  ];
  const trace = normalizeAnswerTrace({
    version: 1,
    steps: [{ ...makeStep(), sources: [...bad.map((url) => ({ ...makeSource(), url })), makeSource({ url: " HTTP://Example.com/ok " })] }],
  });
  assert.deepEqual(trace!.steps[0].sources.map((source) => source.url), ["HTTP://Example.com/ok"]);
});

test("a source gets the server's defaults: url as title, site-root favicon, initial label, clamped depth", () => {
  const trace = normalizeAnswerTrace({
    version: 1,
    steps: [{
      ...makeStep(),
      sources: [{
        url: "https://www.example.com/path?q=1",
        title: " ",
        hostname: "www.example.com",
        favicon_url: "javascript:alert(1)",
        fallback_label: "",
        link_depth: 99,
        linked_from: "x.com",
      }, {
        url: "https://news.example.jp/b",
        link_depth: -3,
      }],
    }],
  });
  assert.deepEqual(trace!.steps[0].sources[0], {
    url: "https://www.example.com/path?q=1",
    title: "https://www.example.com/path?q=1",
    hostname: "www.example.com",
    favicon_url: "https://www.example.com/favicon.ico",
    fallback_label: "E",
    link_depth: 9,
    linked_from: "x.com",
  });
  assert.equal(trace!.steps[0].sources[1].link_depth, 0);
  // ホスト名が無ければ題名（= URL）の頭文字になる（サーバーと同じ）
  // With no hostname the initial comes from the title (the URL), as on the server
  assert.equal(trace!.steps[0].sources[1].fallback_label, "H");
});

test("step ids stay unique: only a missing, malformed or duplicate id is reassigned, to the smallest unused sN", () => {
  const trace = normalizeAnswerTrace({
    version: 1,
    steps: [
      { ...makeStep(), id: "a" },
      { ...makeStep(), id: "a" },
      { ...makeStep(), id: "bad id!" },
      { ...makeStep(), id: undefined },
      { ...makeStep(), id: "s1" },
      { ...makeStep(), id: "s3" },
    ],
  });
  // 使える ID（a・s1・s3）は先に確保されるので、振り直しは s2, s4 になり後ろの元 ID とぶつからない
  // Usable ids (a, s1, s3) are reserved first, so reassignment yields s2 and s4 and never hits a later step's own id
  assert.deepEqual(trace!.steps.map((step) => step.id), ["a", "s2", "s4", "s5", "s1", "s3"]);
});

test("isSameAnswerTrace compares content, not identity", () => {
  assert.equal(isSameAnswerTrace(makeTrace(), makeTrace()), true);
  assert.equal(isSameAnswerTrace(makeTrace(), makeTrace([makeStep({ status: "running" })])), false);
  assert.equal(isSameAnswerTrace(null, makeTrace()), false);
  assert.equal(isSameAnswerTrace(null, null), true);
});

test("withAnswerTracePart puts the trace at the head and replaces any trace already there", () => {
  const trace = makeTrace();
  const older = makeTrace([makeStep({ title: "古い" })]);
  const body: ChatMessagePart = { type: "text", text: "本文" };

  assert.deepEqual(withAnswerTracePart([body], trace), [{ type: "answer_trace", trace }, body]);
  assert.deepEqual(withAnswerTracePart([{ type: "answer_trace", trace: older }, body], trace), [{ type: "answer_trace", trace }, body]);
  assert.deepEqual(withAnswerTracePart([{ type: "legacy_answer_trace", html: "<details></details>" }, body], trace), [
    { type: "answer_trace", trace },
    body,
  ]);
  assert.deepEqual(withAnswerTracePart([body], null), [body]);
  assert.equal(withAnswerTracePart(undefined, null), undefined);
});

test("message parts accept both trace kinds and drop an invalid structured trace", () => {
  const trace = makeTrace([makeStep({ sources: [makeSource()] })], "Web検索1回");
  const parts = normalizeChatMessageParts([
    { type: "text", text: "本文" },
    { type: "answer_trace", trace },
    { type: "legacy_answer_trace", html: "<details></details>" },
  ], undefined, false);

  assert.deepEqual(parts, [
    { type: "answer_trace", trace },
    { type: "text", text: "本文" },
  ]);

  assert.deepEqual(normalizeChatMessageParts([
    { type: "answer_trace", trace: { version: 1, summary: "", steps: [] } },
    { type: "legacy_answer_trace", html: "   " },
    { type: "text", text: "本文" },
  ], undefined, false), [{ type: "text", text: "本文" }]);

  assert.deepEqual(normalizeChatMessageParts([
    { type: "legacy_answer_trace", html: "<details class=\"web-search-sources\"></details>" },
    { type: "text", text: "本文" },
  ], undefined, true), [
    { type: "legacy_answer_trace", html: "<details class=\"web-search-sources\"></details>" },
    { type: "text", text: "本文" },
  ]);
});

test("message parts normalize a trace's sources the same way as the server", () => {
  const parts = normalizeChatMessageParts([{
    type: "answer_trace",
    trace: makeTrace([makeStep({ sources: [makeSource({ url: "javascript:alert(1)" }), makeSource()] })]),
  }], undefined, false);
  assert.equal(parts?.[0].type, "answer_trace");
  if (parts?.[0].type !== "answer_trace") return;
  assert.deepEqual(parts[0].trace.steps[0].sources.map((source) => source.url), ["https://example.com/a"]);
});
