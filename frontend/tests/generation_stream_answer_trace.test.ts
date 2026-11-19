// 生成中に届く回答までのステップ（answer_trace_updated）の扱いを検証する。
// 本文より先・本文の途中・再送・パーツ更新・下書き・再読み込みからの復元のどれでも実行記録が正しく出ることを確かめる。
// Tests how the steps to the answer (answer_trace_updated) are handled while generating: the record must show
// correctly whether it arrives before the prose, in the middle of it, is resent, follows a parts update or a draft,
// or has to be restored after a reload.

import assert from "node:assert/strict";
import test from "node:test";

import { consumeGenerationStream } from "../lib/chat_page/generation_stream_consumer";
import type { ChatMessagePart, UiChatMessage } from "../lib/chat_page/types";
import { makeSource, makeStep, makeTrace } from "./answer_trace_test_data";
import {
  createFakeClock,
  createScriptedStream,
  createStreamHostRecorder,
  flushMicrotasks,
  settleStream,
  sseBlock,
  type FakeClock,
} from "./generation_stream_test_harness";

const encoder = new TextEncoder();

// ブロックを 1 つずつ流し込めるストリーム。途中の画面を観測するために使う。
// A stream whose blocks are pushed one at a time, used to observe the screen in between.
function createControlledStream(generationId = "gen-1") {
  const queue: Array<Uint8Array | null> = [];
  let waiting: ((result: { value: Uint8Array | undefined; done: boolean }) => void) | null = null;
  const deliver = (item: Uint8Array | null) => {
    if (waiting) {
      const resolve = waiting;
      waiting = null;
      resolve(item ? { value: item, done: false } : { value: undefined, done: true });
      return;
    }
    queue.push(item);
  };
  const reader = {
    read: () =>
      new Promise<{ value: Uint8Array | undefined; done: boolean }>((resolve) => {
        if (queue.length > 0) {
          const item = queue.shift()!;
          resolve(item ? { value: item, done: false } : { value: undefined, done: true });
          return;
        }
        waiting = resolve;
      }),
    cancel: async () => undefined,
  };
  const response = {
    ok: true,
    status: 200,
    headers: {
      get: (name: string) => {
        if (name.toLowerCase() === "content-type") return "text/event-stream";
        if (name.toLowerCase() === "x-chat-generation-id") return generationId;
        return null;
      },
    },
    body: { getReader: () => reader, cancel: reader.cancel },
  } as unknown as Response;
  return {
    response,
    push: (block: string) => deliver(encoder.encode(block)),
    end: () => deliver(null),
  };
}

// 流し込んだブロックが処理され、予約済みのフレームが描かれるまで進める。
// Advance until the pushed blocks are processed and the queued frames are drawn.
async function drive(clock: FakeClock, rounds = 12) {
  for (let round = 0; round < rounds; round += 1) {
    await flushMicrotasks();
    clock.runFrames();
    clock.advance(60);
  }
  await flushMicrotasks();
}

function streamingMessage(messages: UiChatMessage[]) {
  return messages.find((message) => message.sender === "assistant" && message.streaming);
}

function partTypes(parts: ChatMessagePart[] | undefined) {
  return (parts ?? []).map((part) => part.type);
}

function bodyText(parts: ChatMessagePart[] | undefined) {
  return (parts ?? []).map((part) => (part.type === "text" ? part.text : "")).join("");
}

const TRACE_1 = makeTrace([makeStep({ id: "s1", status: "running", sources: [makeSource()] })], "");
const TRACE_2 = makeTrace(
  [makeStep({ id: "s1", status: "done", sources: [makeSource()] }), makeStep({ id: "s2", kind: "answer", title: "回答を作成" })],
  "参照サイト1件",
);

test("a trace that arrives before the prose waits for the bubble and then leads its parts", async () => {
  const clock = createFakeClock();
  const recorder = createStreamHostRecorder({ clock });
  recorder.host.messages.updateActiveMessages(() => [
    { id: "thinking-0", sender: "thinking", text: "思考中", generationPhase: "preparing" },
  ]);
  const stream = createControlledStream();
  const consumed = consumeGenerationStream(stream.response, recorder.host);

  stream.push(sseBlock(1, "answer_trace_updated", { trace: TRACE_1 }));
  await drive(clock);
  // 実行記録だけでは吹き出しを作らず、思考中の表示を残す
  // A record alone creates no bubble, so the thinking indicator stays
  assert.equal(streamingMessage(recorder.messages()), undefined);
  assert.equal(recorder.messages()[0]?.sender, "thinking");

  stream.push(sseBlock(2, "chunk", { text: "京都の紅葉は見頃です。" }));
  await drive(clock);
  const message = streamingMessage(recorder.messages());
  assert.deepEqual(partTypes(message?.parts), ["answer_trace", "text"]);
  assert.equal(message?.parts?.[0].type === "answer_trace" && message.parts[0].trace.steps[0].status, "running");
  assert.ok(bodyText(message?.parts).startsWith("京都"));
  assert.equal(message?.text, bodyText(message?.parts));

  stream.push(sseBlock(3, "done", { response: "京都の紅葉は見頃です。", parts: [
    { type: "answer_trace", trace: TRACE_2 },
    { type: "text", text: "京都の紅葉は見頃です。" },
  ] }));
  stream.end();
  assert.equal(await settleStream(consumed, clock), true);

  // 確定後はサーバーの終端パーツが正になる
  // After completion the server's terminal parts are the truth
  const final = recorder.messages().find((entry) => entry.sender === "assistant");
  assert.equal(final?.streaming, false);
  assert.deepEqual(final?.parts, [
    { type: "answer_trace", trace: TRACE_2 },
    { type: "text", text: "京都の紅葉は見頃です。" },
  ]);
  assert.equal(final?.text, "京都の紅葉は見頃です。");
});

test("a trace that arrives in the middle of the prose joins the same bubble without disturbing the text", async () => {
  const clock = createFakeClock();
  const recorder = createStreamHostRecorder({ clock });
  const stream = createControlledStream();
  const consumed = consumeGenerationStream(stream.response, recorder.host);

  stream.push(sseBlock(1, "chunk", { text: "京都の紅葉は" }));
  await drive(clock);
  const before = streamingMessage(recorder.messages());
  assert.equal(before?.parts, undefined);

  stream.push(sseBlock(2, "answer_trace_updated", { trace: TRACE_1 }));
  await drive(clock);
  const during = streamingMessage(recorder.messages());
  assert.equal(during?.id, before?.id);
  assert.deepEqual(partTypes(during?.parts), ["answer_trace", "text"]);
  assert.equal(during?.text, before?.text);

  stream.push(sseBlock(3, "chunk", { text: "11月中旬が見頃です。" }));
  stream.push(sseBlock(4, "done", { response: "京都の紅葉は11月中旬が見頃です。" }));
  stream.end();
  assert.equal(await settleStream(consumed, clock), true);

  const final = recorder.messages().find((entry) => entry.sender === "assistant");
  // 終端にパーツが無くても、受信済みの実行記録を先頭に載せて確定する
  // With no terminal parts, the received record still leads the settled message
  assert.deepEqual(partTypes(final?.parts), ["answer_trace", "text"]);
  assert.equal(final?.text, "京都の紅葉は11月中旬が見頃です。");
});

test("a later snapshot replaces the earlier one and a resent identical one changes nothing", async () => {
  const clock = createFakeClock();
  const recorder = createStreamHostRecorder({ clock });
  const stream = createControlledStream();
  const consumed = consumeGenerationStream(stream.response, recorder.host);

  stream.push(sseBlock(1, "chunk", { text: "本文" }));
  stream.push(sseBlock(2, "answer_trace_updated", { trace: TRACE_1 }));
  await drive(clock);
  const first = streamingMessage(recorder.messages())?.parts?.[0];

  stream.push(sseBlock(3, "answer_trace_updated", { trace: TRACE_1 }));
  await drive(clock);
  assert.equal(streamingMessage(recorder.messages())?.parts?.[0], first);

  stream.push(sseBlock(4, "answer_trace_updated", { trace: TRACE_2 }));
  await drive(clock);
  const replaced = streamingMessage(recorder.messages())?.parts?.[0];
  assert.equal(replaced?.type === "answer_trace" && replaced.trace.steps.length, 2);

  stream.push(sseBlock(5, "done", { response: "本文" }));
  stream.end();
  await settleStream(consumed, clock);
});

test("a parts update does not erase the received record", async () => {
  const clock = createFakeClock();
  const recorder = createStreamHostRecorder({ clock });
  const stream = createControlledStream();
  const consumed = consumeGenerationStream(stream.response, recorder.host);
  const image: ChatMessagePart = {
    type: "web_search_image",
    image: { url: "https://cdn.example.com/a.jpg", alt: "a", sourceUrl: "https://example.com/a" },
  };

  stream.push(sseBlock(1, "answer_trace_updated", { trace: TRACE_2 }));
  stream.push(sseBlock(2, "chunk", { text: "京都の紅葉。" }));
  await drive(clock);
  stream.push(sseBlock(3, "response_parts_updated", {
    response: "京都の紅葉。続き",
    parts: [{ type: "text", text: "京都の紅葉。" }, { type: "web_search_image", image: { url: "https://cdn.example.com/a.jpg", alt: "a", source_url: "https://example.com/a" } }, { type: "text", text: "続き" }],
  }));
  await drive(clock);

  const message = streamingMessage(recorder.messages());
  assert.deepEqual(partTypes(message?.parts), ["answer_trace", "text", "web_search_image", "text"]);
  assert.deepEqual(message?.parts?.[2], image);

  stream.push(sseBlock(4, "done", { response: "京都の紅葉。続き" }));
  stream.end();
  await settleStream(consumed, clock);
});

test("a trace does not cancel the draft shown ahead of confirmation", async () => {
  const clock = createFakeClock();
  const recorder = createStreamHostRecorder({ clock });
  const stream = createControlledStream();
  const consumed = consumeGenerationStream(stream.response, recorder.host);

  stream.push(sseBlock(null, "answer_draft", { text: "下書きの本文です。" }));
  await drive(clock);
  assert.ok(streamingMessage(recorder.messages())?.text.startsWith("下書き"));

  stream.push(sseBlock(1, "answer_trace_updated", { trace: TRACE_1 }));
  await drive(clock);
  const message = streamingMessage(recorder.messages());
  assert.ok(message?.text.startsWith("下書き"), "the draft text is still shown");
  assert.deepEqual(partTypes(message?.parts), ["answer_trace", "text"]);

  stream.push(sseBlock(2, "answer_draft_reset", { confirming: true }));
  stream.push(sseBlock(3, "chunk", { text: "確定した本文です。" }));
  stream.push(sseBlock(4, "done", { response: "確定した本文です。" }));
  stream.end();
  assert.equal(await settleStream(consumed, clock), true);
  const final = recorder.messages().find((entry) => entry.sender === "assistant");
  assert.equal(final?.text, "確定した本文です。");
  assert.equal(partTypes(final?.parts)[0], "answer_trace");
});

test("a draft bubble dropped by a retry keeps the record for the next bubble", async () => {
  const clock = createFakeClock();
  const recorder = createStreamHostRecorder({ clock });
  recorder.host.messages.updateActiveMessages(() => [
    { id: "thinking-0", sender: "thinking", text: "思考中", generationPhase: "preparing" },
  ]);
  const stream = createControlledStream();
  const consumed = consumeGenerationStream(stream.response, recorder.host);

  stream.push(sseBlock(null, "answer_draft", { text: "下書き" }));
  stream.push(sseBlock(1, "answer_trace_updated", { trace: TRACE_1 }));
  stream.push(sseBlock(2, "answer_draft_reset", { confirming: false }));
  await drive(clock);
  assert.equal(streamingMessage(recorder.messages()), undefined);

  stream.push(sseBlock(3, "chunk", { text: "確定本文" }));
  await drive(clock);
  assert.deepEqual(partTypes(streamingMessage(recorder.messages())?.parts), ["answer_trace", "text"]);

  stream.push(sseBlock(4, "done", { response: "確定本文" }));
  stream.end();
  await settleStream(consumed, clock);
});

test("an interrupted generation saves the received record with the text it has", async () => {
  const clock = createFakeClock();
  const recorder = createStreamHostRecorder({ clock });
  const stream = createControlledStream();
  const consumed = consumeGenerationStream(stream.response, recorder.host);

  stream.push(sseBlock(1, "answer_trace_updated", { trace: TRACE_2 }));
  stream.push(sseBlock(2, "chunk", { text: "途中までの本文" }));
  stream.push(sseBlock(3, "error", { message: "失敗しました" }));
  stream.end();
  assert.equal(await settleStream(consumed, clock), false);

  const saved = recorder.persistedAnswers()[0];
  assert.equal(saved?.text, "途中までの本文");
  assert.deepEqual(partTypes(saved?.parts), ["answer_trace", "text"]);
});

test("an incomplete generation without terminal parts still shows the received record", async () => {
  const clock = createFakeClock();
  const recorder = createStreamHostRecorder({ clock });
  const stream = createControlledStream();
  const consumed = consumeGenerationStream(stream.response, recorder.host);

  stream.push(sseBlock(1, "answer_trace_updated", { trace: TRACE_2 }));
  stream.push(sseBlock(2, "chunk", { text: "途中" }));
  stream.push(sseBlock(3, "incomplete", { response: "途中", message: "途中で終了" }));
  stream.end();
  await settleStream(consumed, clock);

  const final = recorder.messages().find((entry) => entry.sender === "assistant" && !entry.error);
  assert.equal(final?.partial, true);
  assert.deepEqual(partTypes(final?.parts), ["answer_trace", "text"]);
});

test("the record is saved with the event id so a reload can restore it", async () => {
  const clock = createFakeClock();
  const recorder = createStreamHostRecorder({
    clock,
    storedGeneration: {
      roomId: "room-1", roomMode: "normal", generationId: "gen-1", lastEventId: 0, streamedText: "", updatedAt: Date.now(),
    },
  });
  const stream = createControlledStream("gen-1");
  const consumed = consumeGenerationStream(stream.response, recorder.host);

  stream.push(sseBlock(4, "answer_trace_updated", { trace: TRACE_1 }));
  await drive(clock);

  const stored = recorder.storedGeneration();
  assert.equal(stored?.lastEventId, 4);
  assert.deepEqual(stored?.answerTrace, TRACE_1);

  stream.push(sseBlock(5, "done", { response: "本文" }));
  stream.end();
  await settleStream(consumed, clock);
});

test("after a reload the saved record shows with the restored text and a resent snapshot is not needed", async () => {
  const clock = createFakeClock();
  const recorder = createStreamHostRecorder({
    clock,
    storedGeneration: {
      roomId: "room-1", roomMode: "normal", generationId: "gen-1", lastEventId: 4, streamedText: "復元した本文", answerTrace: TRACE_1,
      updatedAt: Date.now(),
    },
  });
  recorder.lastEventIds.set("room-1", 4);
  const stream = createControlledStream("gen-1");
  const consumed = consumeGenerationStream(stream.response, recorder.host);
  await drive(clock);

  // 再接続は Last-Event-ID より後しか再送しないので、保存しておいた記録だけで先頭に出る
  // The reconnect replays only after Last-Event-ID, so the saved record alone leads the parts
  const restored = streamingMessage(recorder.messages());
  assert.deepEqual(partTypes(restored?.parts), ["answer_trace", "text"]);
  assert.equal(restored?.text, "復元した本文");

  stream.push(sseBlock(5, "answer_trace_updated", { trace: TRACE_2 }));
  await drive(clock);
  const updated = streamingMessage(recorder.messages())?.parts?.[0];
  assert.equal(updated?.type === "answer_trace" && updated.trace.steps.length, 2);

  stream.push(sseBlock(6, "done", { response: "復元した本文" }));
  stream.end();
  assert.equal(await settleStream(consumed, clock), true);
});

test("a different generation does not inherit the previous record", async () => {
  const clock = createFakeClock();
  const recorder = createStreamHostRecorder({
    clock,
    storedGeneration: {
      roomId: "room-1", roomMode: "normal", generationId: "old-generation", lastEventId: 9, streamedText: "前回", answerTrace: TRACE_2,
      updatedAt: Date.now(),
    },
  });
  const stream = createScriptedStream([
    sseBlock(1, "chunk", { text: "今回の回答" }),
    sseBlock(2, "done", { response: "今回の回答" }),
  ], { generationId: "new-generation" });

  assert.equal(await settleStream(consumeGenerationStream(stream.response, recorder.host), clock), true);
  const final = recorder.messages().find((entry) => entry.sender === "assistant");
  assert.equal(final?.text, "今回の回答");
  assert.equal(final?.parts?.some((part) => part.type === "answer_trace") ?? false, false);
});
