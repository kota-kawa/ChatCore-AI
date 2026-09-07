import assert from "node:assert/strict";
import test from "node:test";

import {
  interpretGenerationStreamEvent,
  type GenerationStreamAction,
} from "../lib/chat_page/generation_stream_events";
import { parseStreamEventBlock } from "../lib/chat_page/streaming";
import type { StreamParsedEvent } from "../lib/chat_page/types";

// 表示文言の言語差ではなく、選ばれた分岐を検証する。
// Assert the branch that was chosen, not the wording of either locale.
const localizeJa = (ja: string) => ja;
const localizeEn = (_ja: string, en: string) => en;

function interpret(
  event: string,
  data: Record<string, unknown>,
  streamedText = "",
  localize: (ja: string, en: string) => string = localizeJa,
): GenerationStreamAction {
  const parsed: StreamParsedEvent = { event, data };
  return interpretGenerationStreamEvent(parsed, { streamedText, localize });
}

test("a chunk event carries its text through", () => {
  assert.deepEqual(interpret("chunk", { text: "こんにちは" }), { kind: "chunk", text: "こんにちは" });
});

test("a chunk event with no usable text changes nothing", () => {
  assert.deepEqual(interpret("chunk", { text: "" }), { kind: "ignored" });
  assert.deepEqual(interpret("chunk", { text: 42 }), { kind: "ignored" });
  assert.deepEqual(interpret("chunk", {}), { kind: "ignored" });
});

test("an unknown event name changes nothing", () => {
  assert.deepEqual(interpret("something_new", { text: "x" }), { kind: "ignored" });
  assert.deepEqual(interpret("message", { text: "x" }), { kind: "ignored" });
});

test("a done event finalizes with the payload response", () => {
  const action = interpret("done", { response: "完成した回答", room_title: "紅葉の話" }, "途中まで");

  assert.equal(action.kind, "done");
  assert.deepEqual(action, {
    kind: "done",
    roomTitle: "紅葉の話",
    responseText: "完成した回答",
    parts: undefined,
  });
});

test("a done event without a response falls back to the received text", () => {
  const action = interpret("done", {}, "受信済みの本文");

  assert.equal(action.kind, "done");
  if (action.kind !== "done") return;
  assert.equal(action.responseText, "受信済みの本文");
});

// 空の完了は「回答なし」。空の吹き出しを残さずエラーとして扱う。
// An empty completion means no answer, so it becomes an error, not a blank bubble.
test("a done event with neither text nor answer parts reports an empty answer", () => {
  const action = interpret("done", { response: "   ", room_title: "題名" });

  assert.equal(action.kind, "empty_answer");
  if (action.kind !== "empty_answer") return;
  assert.equal(action.roomTitle, "題名");
  assert.match(action.message, /空/);
});

test("a done event carrying only web-search images still reports an empty answer", () => {
  const action = interpret("done", {
    response: "",
    parts: [
      {
        type: "web_search_image",
        image: {
          url: "https://cdn.example.com/maple.jpg",
          alt: "紅葉",
          source_url: "https://example.com/kyoto",
          source_title: "京都",
        },
      },
    ],
  });

  assert.equal(action.kind, "empty_answer");
});

test("a done event carrying a non-image part is a real answer", () => {
  const action = interpret("done", {
    response: "",
    parts: [{ type: "text", text: "画像の説明" }],
  });

  assert.equal(action.kind, "done");
  if (action.kind !== "done") return;
  assert.deepEqual(action.parts, [{ type: "text", text: "画像の説明" }]);
});

test("an incomplete event keeps the partial text and the server message", () => {
  const action = interpret(
    "incomplete",
    { response: "途中までの回答", message: "途中までの回答を保存しました。", room_title: "調査" },
    "途中まで",
  );

  assert.deepEqual(action, {
    kind: "incomplete",
    roomTitle: "調査",
    finalText: "途中までの回答",
    parts: undefined,
    message: "途中までの回答を保存しました。",
  });
});

test("an incomplete event without a message uses the localized fallback", () => {
  const ja = interpret("incomplete", {}, "途中まで");
  const en = interpret("incomplete", {}, "partial", localizeEn);

  assert.equal(ja.kind, "incomplete");
  if (ja.kind !== "incomplete") return;
  assert.match(ja.message, /途中/);
  assert.equal(en.kind, "incomplete");
  if (en.kind !== "incomplete") return;
  assert.match(en.message, /ended early/);
});

test("an aborted event prefers the text the server persisted on stop", () => {
  const action = interpret("aborted", { response: "サーバーが保存した本文" }, "クライアント側の本文");

  assert.deepEqual(action, { kind: "aborted", finalText: "サーバーが保存した本文", parts: undefined });
});

test("an aborted event without a response keeps what the client already has", () => {
  const action = interpret("aborted", {}, "クライアント側の本文");

  assert.equal(action.kind, "aborted");
  if (action.kind !== "aborted") return;
  assert.equal(action.finalText, "クライアント側の本文");
});

test("an error event carries the server message, or a localized fallback", () => {
  assert.deepEqual(interpret("error", { message: "上限に達しました" }), {
    kind: "error",
    message: "上限に達しました",
  });

  const fallback = interpret("error", {}, "", localizeEn);
  assert.equal(fallback.kind, "error");
  if (fallback.kind !== "error") return;
  assert.match(fallback.message, /error occurred while streaming/);
});

test("a parts update replaces the displayed text without pacing it", () => {
  const action = interpret("response_parts_updated", {
    response: "画像付きの回答",
    parts: [{ type: "text", text: "画像付きの回答" }],
  });

  assert.deepEqual(action, {
    kind: "parts_updated",
    displayText: "画像付きの回答",
    parts: [{ type: "text", text: "画像付きの回答" }],
  });
});

test("a parts update without a response falls back to the streamed text", () => {
  const action = interpret("response_parts_updated", {}, "受信済み");

  assert.deepEqual(action, { kind: "parts_updated", displayText: "受信済み", parts: null });
});

test("web-search status events map to the thinking phases", () => {
  assert.deepEqual(interpret("web_search_started", {}), {
    kind: "thinking_status",
    text: "Web検索中",
    phase: "web-search",
  });
  assert.deepEqual(interpret("web_search_completed", {}), {
    kind: "thinking_status",
    text: "検索結果を読み込んでいます",
    phase: "web-search",
  });
});

// 表示は安定コードから決める。ローカライズ済み文言からは推測しない。
// The status comes from the stable code, never from a localized message.
test("a web-search failure picks its wording from the stable failure code", () => {
  const configuration = interpret("web_search_failed", { code: "web_search.configuration" });
  const quota = interpret("web_search_failed", { code: "web_search.quota_exceeded" });
  const unknown = interpret("web_search_failed", { code: "totally_unknown" });

  assert.equal(configuration.kind, "thinking_status");
  if (configuration.kind !== "thinking_status") return;
  assert.match(configuration.text, /検索設定/);
  assert.equal(configuration.phase, "generating");

  assert.equal(quota.kind, "thinking_status");
  if (quota.kind !== "thinking_status") return;
  assert.match(quota.text, /上限/);

  assert.equal(unknown.kind, "thinking_status");
  if (unknown.kind !== "thinking_status") return;
  assert.match(unknown.text, /Web検索に失敗/);
});

test("shared-prompt search results distinguish hits, zero hits and prefetched queries", () => {
  const hit = interpret("shared_prompt_search_completed", { prompt_count: 3 });
  const empty = interpret("shared_prompt_search_completed", { prompt_count: 0 });
  const prefetched = interpret("shared_prompt_search_completed", { status: "already_searched" });

  assert.equal(hit.kind === "thinking_status" && hit.phase, "web-search");
  assert.equal(empty.kind === "thinking_status" && empty.phase, "generating");
  // 事前検索済みは0件扱いにしない / a prefetched query must not read as zero hits
  assert.equal(prefetched.kind === "thinking_status" && prefetched.phase, "web-search");
});

test("personal-knowledge results count memos and context facts together", () => {
  const factsOnly = interpret("personal_knowledge_search_completed", {
    memo_count: 0,
    context_fact_count: 2,
  });
  const nothing = interpret("personal_knowledge_search_completed", {
    memo_count: 0,
    context_fact_count: 0,
  });

  assert.equal(factsOnly.kind === "thinking_status" && factsOnly.phase, "web-search");
  assert.equal(nothing.kind === "thinking_status" && nothing.phase, "generating");
});

test("search failures and the generation start move the thinking status on", () => {
  assert.equal(
    interpret("shared_prompt_search_failed", {}).kind === "thinking_status"
      && (interpret("shared_prompt_search_failed", {}) as { phase: string }).phase,
    "generating",
  );
  assert.deepEqual(interpret("response_generation_started", {}), {
    kind: "thinking_status",
    text: "思考中",
    phase: "generating",
  });
  assert.deepEqual(interpret("personal_knowledge_search_started", {}), {
    kind: "thinking_status",
    text: "メモとマイコンテキストを検索しています",
    phase: "web-search",
  });
});

// 壊れたイベントブロックは parse 段階で捨てられ、解釈まで届かない。
// A malformed event block is dropped while parsing and never reaches interpretation.
test("malformed event blocks are rejected before interpretation", () => {
  assert.equal(parseStreamEventBlock("event: chunk\ndata: {not json}"), null);
  assert.equal(parseStreamEventBlock("event: chunk"), null);
  assert.equal(parseStreamEventBlock(""), null);
  assert.equal(parseStreamEventBlock("data: 42"), null);
});
