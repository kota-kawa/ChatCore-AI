import assert from "node:assert/strict";
import test from "node:test";

import { consumeGenerationStream } from "../lib/chat_page/generation_stream_consumer";
import type { UiChatMessage } from "../lib/chat_page/types";
import {
  createFakeClock,
  createScriptedStream,
  createStreamHostRecorder,
  flushMicrotasks,
  rawSseBlock,
  settleStream,
  sseBlock,
  type FakeClock,
} from "./generation_stream_test_harness";

function assistantMessages(messages: UiChatMessage[]) {
  return messages.filter((message) => message.sender === "assistant");
}

function jsonResponse(status: number) {
  return { ok: status >= 200 && status < 300, status, headers: { get: () => "application/json" } } as unknown as Response;
}

// 「思考中」だけが並んでいる初期状態を作る。
// Start from the state the hook leaves behind: a lone thinking placeholder.
function seedThinkingMessage(recorder: ReturnType<typeof createStreamHostRecorder>) {
  recorder.host.messages.updateActiveMessages(() => [
    { id: "thinking-0", sender: "thinking", text: "思考中", generationPhase: "preparing" },
  ]);
}

// ---------------------------------------------------------------------------
// 通常のストリーミング / a normal streaming sequence
// ---------------------------------------------------------------------------

test("a normal streaming sequence renders, finalizes and persists the answer", async () => {
  const clock = createFakeClock();
  const recorder = createStreamHostRecorder({ clock });
  seedThinkingMessage(recorder);

  const stream = createScriptedStream([
    sseBlock(1, "response_generation_started", {}),
    sseBlock(2, "chunk", { text: "こんにちは" }),
    sseBlock(3, "chunk", { text: "。元気ですか" }),
    sseBlock(4, "done", { response: "こんにちは。元気ですか", room_title: "あいさつ" }),
  ]);

  const completed = await settleStream(consumeGenerationStream(stream.response, recorder.host), clock);

  assert.equal(completed, true);
  const answers = assistantMessages(recorder.messages());
  assert.equal(answers.length, 1);
  assert.equal(answers[0].text, "こんにちは。元気ですか");
  // 完了後は演出を外し、途中保存の印も付けない。
  // After completion the reveal state is off and no partial marker is set.
  assert.equal(answers[0].streaming, false);
  assert.equal(answers[0].partial, false);
  // 「思考中」は確定描画で取り除かれる / the thinking placeholder is gone
  assert.equal(recorder.messages().some((message) => message.sender === "thinking"), false);
  assert.deepEqual(recorder.persistedAnswers(), [{ text: "こんにちは。元気ですか", sender: "bot" }]);
  assert.deepEqual(recorder.roomTitles(), ["あいさつ"]);
  assert.deepEqual(recorder.errors(), []);
  // 完了時は再開位置を捨て、進行状態も消す。
  // On completion the resume position and the progress state are dropped.
  assert.equal(recorder.lastEventIds.has("room-1"), false);
  assert.ok(recorder.generationStateClears() >= 1);
});

// 文字送りは1フレームずつ進む。完了前の途中フレームでは全文が出ていない。
// The reveal advances frame by frame: a mid-flight frame shows less than the whole answer.
test("streamed text is revealed gradually instead of appearing all at once", async () => {
  const clock = createFakeClock();
  const recorder = createStreamHostRecorder({ clock });
  seedThinkingMessage(recorder);

  const longAnswer = "これは文字送りの速度を確かめるための十分に長い日本語の回答です。".repeat(4);
  const stream = createScriptedStream([sseBlock(1, "chunk", { text: longAnswer })]);

  const consuming = consumeGenerationStream(stream.response, recorder.host);
  await flushMicrotasks();

  // 表示は REVEAL_CHUNK_STEP_CHARS の刻みでしか伸びないため、1刻みを超えるだけの
  // フレームを実時間に近い間隔で進める。数十msだと刻み未満で「0文字」に丸められる。
  // The visible length only grows in REVEAL_CHUNK_STEP_CHARS steps, so advance
  // enough frames at a realistic interval to cross one step; a few tens of
  // milliseconds still rounds down to zero characters.
  for (let frame = 0; frame < 12; frame += 1) {
    clock.runFrames();
    clock.advance(16);
  }
  clock.runFrames();
  await flushMicrotasks();

  const streaming = assistantMessages(recorder.messages())[0];
  assert.equal(streaming.streaming, true);
  assert.ok(streaming.text.length > 0, "some text should already be visible");
  assert.ok(
    streaming.text.length < longAnswer.length,
    `expected a partial reveal, got ${streaming.text.length}/${longAnswer.length}`,
  );

  recorder.setActive(false);
  await settleStream(consuming, clock);
});

// ---------------------------------------------------------------------------
// 途中で切れたストリーム / a stream that ends mid-message
// ---------------------------------------------------------------------------

test("a stream that ends mid-message reconnects from the last event id", async () => {
  const clock = createFakeClock();
  const resumed = createScriptedStream([
    sseBlock(3, "chunk", { text: "続きです。" }),
    sseBlock(4, "done", { response: "途中まで。続きです。" }),
  ]);
  const reconnectRequests: number[] = [];

  const recorder = createStreamHostRecorder({
    clock,
    openStream: (lastEventId) => {
      reconnectRequests.push(lastEventId);
      return Promise.resolve(resumed.response);
    },
  });
  seedThinkingMessage(recorder);

  // done を返さずに終わるレスポンス = 途中切断。
  // A response that ends without "done" is an interrupted stream.
  const interrupted = createScriptedStream([
    sseBlock(1, "chunk", { text: "途中" }),
    sseBlock(2, "chunk", { text: "まで。" }),
  ]);

  const completed = await settleStream(consumeGenerationStream(interrupted.response, recorder.host), clock);

  assert.equal(completed, true);
  // 最後に処理したイベントIDから再開する / resumes from the last processed event id
  assert.deepEqual(reconnectRequests, [2]);
  const answers = assistantMessages(recorder.messages());
  assert.equal(answers.length, 1);
  assert.equal(answers[0].text, "途中まで。続きです。");
  assert.deepEqual(recorder.errors(), []);
});

test("a mid-message network error resumes rather than failing the turn", async () => {
  const clock = createFakeClock();
  const resumed = createScriptedStream([sseBlock(2, "done", { response: "最後まで届きました" })]);
  const recorder = createStreamHostRecorder({
    clock,
    openStream: () => Promise.resolve(resumed.response),
  });
  seedThinkingMessage(recorder);

  const dropped = createScriptedStream([
    sseBlock(1, "chunk", { text: "途中" }),
    { error: new TypeError("Failed to fetch") },
  ]);

  const completed = await settleStream(consumeGenerationStream(dropped.response, recorder.host), clock);

  assert.equal(completed, true);
  assert.equal(assistantMessages(recorder.messages())[0].text, "最後まで届きました");
  assert.deepEqual(recorder.errors(), []);
});

// サーバー側に生成が残っていない（4xx）なら、ここまでの本文を保存して終える。
// When the server no longer has the generation (4xx), save what arrived and stop.
test("an unresumable reconnect saves the partial answer and reports it once", async () => {
  const clock = createFakeClock();
  const recorder = createStreamHostRecorder({
    clock,
    openStream: () => Promise.resolve(jsonResponse(404)),
  });
  seedThinkingMessage(recorder);

  const interrupted = createScriptedStream([sseBlock(1, "chunk", { text: "ここまでの回答" })]);

  const completed = await settleStream(consumeGenerationStream(interrupted.response, recorder.host), clock);

  assert.equal(completed, false);
  const answers = assistantMessages(recorder.messages());
  assert.equal(answers.length, 2);
  assert.equal(answers[0].text, "ここまでの回答");
  assert.equal(answers[0].error, undefined);
  assert.equal(answers[1].error, true);
  assert.equal(recorder.errors().length, 1);
  assert.match(recorder.errors()[0], /ストリームを再開できませんでした/);
  assert.deepEqual(recorder.persistedAnswers(), [{ text: "ここまでの回答", sender: "bot" }]);
});

// 1文字も届いていないなら、呼び出し側へ委譲してユーザー発話ごと取り消させる。
// With nothing received at all, the caller rolls the user's own message back.
test("an unresumable reconnect with no text delegates to the unanswered-failure handler", async () => {
  const clock = createFakeClock();
  const recorder = createStreamHostRecorder({
    clock,
    withUnansweredFailureHandler: true,
    openStream: () => Promise.resolve(jsonResponse(403)),
  });
  seedThinkingMessage(recorder);

  const interrupted = createScriptedStream([sseBlock(1, "response_generation_started", {})]);

  const completed = await settleStream(consumeGenerationStream(interrupted.response, recorder.host), clock);

  assert.equal(completed, false);
  assert.equal(recorder.unansweredFailures().length, 1);
  assert.match(recorder.unansweredFailures()[0], /ストリームを再開できませんでした/);
  // 委譲したときは、この層ではエラー吹き出しを出さない。
  // When delegated, this layer must not append an error bubble of its own.
  assert.deepEqual(recorder.errors(), []);
});

test("an incomplete event keeps the partial answer and marks it as partial", async () => {
  const clock = createFakeClock();
  const recorder = createStreamHostRecorder({ clock });
  seedThinkingMessage(recorder);

  const stream = createScriptedStream([
    sseBlock(1, "chunk", { text: "途中までの回答" }),
    sseBlock(2, "incomplete", { response: "途中までの回答", message: "途中までの回答を保存しました。" }),
  ]);

  const completed = await settleStream(consumeGenerationStream(stream.response, recorder.host), clock);

  assert.equal(completed, true);
  const answers = assistantMessages(recorder.messages());
  assert.equal(answers.length, 2);
  assert.equal(answers[0].text, "途中までの回答");
  assert.equal(answers[0].partial, true);
  assert.equal(answers[1].error, true);
  assert.deepEqual(recorder.errors(), ["途中までの回答を保存しました。"]);
  // incomplete はサーバー側が保存済みなので、端末側では保存しない。
  // The server already saved it, so the device must not persist it again.
  assert.deepEqual(recorder.persistedAnswers(), []);
});

// ---------------------------------------------------------------------------
// 中断 / aborts
// ---------------------------------------------------------------------------

test("a generation that is no longer active stops without touching the screen", async () => {
  const clock = createFakeClock();
  const recorder = createStreamHostRecorder({ clock });
  seedThinkingMessage(recorder);
  const before = recorder.messages();

  recorder.setActive(false);
  const stream = createScriptedStream([sseBlock(1, "chunk", { text: "届いてはいけない" })]);

  const completed = await settleStream(consumeGenerationStream(stream.response, recorder.host), clock);

  assert.equal(completed, false);
  assert.deepEqual(recorder.messages(), before);
  assert.deepEqual(recorder.errors(), []);
  assert.deepEqual(recorder.persistedAnswers(), []);
});

test("an abort mid-stream ends the read without an error bubble", async () => {
  const clock = createFakeClock();
  const recorder = createStreamHostRecorder({ clock });
  seedThinkingMessage(recorder);

  const stream = createScriptedStream([
    sseBlock(1, "chunk", { text: "途中" }),
    { error: new DOMException("Aborted", "AbortError") },
  ]);

  recorder.abortController.abort();
  const completed = await settleStream(consumeGenerationStream(stream.response, recorder.host), clock);

  assert.equal(completed, false);
  assert.deepEqual(recorder.errors(), []);
  assert.deepEqual(recorder.persistedAnswers(), []);
});

// 停止時にサーバーが保存した本文を優先して表示する。
// The text the server persisted on stop takes precedence.
test("a server-side aborted event keeps the text the server saved", async () => {
  const clock = createFakeClock();
  const recorder = createStreamHostRecorder({ clock });
  seedThinkingMessage(recorder);

  const stream = createScriptedStream([
    sseBlock(1, "chunk", { text: "クライアント側" }),
    sseBlock(2, "aborted", { response: "サーバーが保存した本文" }),
  ]);

  const completed = await settleStream(consumeGenerationStream(stream.response, recorder.host), clock);

  assert.equal(completed, true);
  const answers = assistantMessages(recorder.messages());
  assert.equal(answers.length, 1);
  assert.equal(answers[0].text, "サーバーが保存した本文");
  assert.equal(answers[0].streaming, false);
  // 停止時の保存はサーバー側の責務 / persistence on stop belongs to the server
  assert.deepEqual(recorder.persistedAnswers(), []);
  assert.deepEqual(recorder.errors(), []);
});

// ---------------------------------------------------------------------------
// 壊れたイベント / malformed events
// ---------------------------------------------------------------------------

test("a malformed event block is skipped and the rest of the stream still completes", async () => {
  const clock = createFakeClock();
  const recorder = createStreamHostRecorder({ clock });
  seedThinkingMessage(recorder);

  const stream = createScriptedStream([
    sseBlock(1, "chunk", { text: "前半" }),
    rawSseBlock(2, "chunk", "{壊れたJSON"),
    "event: chunk\n\n",
    "\n\n",
    sseBlock(3, "chunk", { text: "後半" }),
    sseBlock(4, "done", { response: "前半後半" }),
  ]);

  const completed = await settleStream(consumeGenerationStream(stream.response, recorder.host), clock);

  assert.equal(completed, true);
  assert.equal(assistantMessages(recorder.messages())[0].text, "前半後半");
  assert.deepEqual(recorder.errors(), []);
});

// 壊れたブロックでイベントIDを進めないので、その番号は後から再利用できる。
// A malformed block must not advance the event id, so the number stays usable.
test("a malformed block does not advance the remembered event id", async () => {
  const clock = createFakeClock();
  const recorder = createStreamHostRecorder({ clock });
  seedThinkingMessage(recorder);

  const stream = createScriptedStream([
    sseBlock(1, "chunk", { text: "有効" }),
    rawSseBlock(5, "chunk", "壊れている"),
  ]);

  recorder.setActive(true);
  const consuming = consumeGenerationStream(stream.response, recorder.host);
  await flushMicrotasks();
  clock.runFrames();
  await flushMicrotasks();
  assert.equal(recorder.lastEventIds.get("room-1"), 1);

  recorder.setActive(false);
  await settleStream(consuming, clock);
});

test("an out-of-order replayed event id is ignored so text is not duplicated", async () => {
  const clock = createFakeClock();
  const recorder = createStreamHostRecorder({ clock });
  seedThinkingMessage(recorder);

  const stream = createScriptedStream([
    sseBlock(2, "chunk", { text: "新しい" }),
    sseBlock(1, "chunk", { text: "古い" }),
    sseBlock(3, "done", {}),
  ]);

  const completed = await settleStream(consumeGenerationStream(stream.response, recorder.host), clock);

  assert.equal(completed, true);
  assert.equal(assistantMessages(recorder.messages())[0].text, "新しい");
});

test("an empty done event is reported as a failure instead of a blank bubble", async () => {
  const clock = createFakeClock();
  const recorder = createStreamHostRecorder({ clock, withUnansweredFailureHandler: true });
  seedThinkingMessage(recorder);

  const stream = createScriptedStream([sseBlock(1, "done", { response: "" })]);

  const completed = await settleStream(consumeGenerationStream(stream.response, recorder.host), clock);

  assert.equal(completed, false);
  assert.equal(recorder.unansweredFailures().length, 1);
  assert.match(recorder.unansweredFailures()[0], /空/);
  assert.deepEqual(recorder.persistedAnswers(), []);
  assert.equal(assistantMessages(recorder.messages()).length, 0);
});

test("a stream error after some text saves what arrived and appends one error", async () => {
  const clock = createFakeClock();
  const recorder = createStreamHostRecorder({ clock });
  seedThinkingMessage(recorder);

  const stream = createScriptedStream([
    sseBlock(1, "chunk", { text: "部分的な回答" }),
    sseBlock(2, "error", { message: "生成に失敗しました。" }),
  ]);

  const completed = await settleStream(consumeGenerationStream(stream.response, recorder.host), clock);

  assert.equal(completed, false);
  assert.equal(recorder.errors().length, 1);
  assert.match(recorder.errors()[0], /生成に失敗しました。 ここまでの応答を保存しました。/);
  assert.deepEqual(recorder.persistedAnswers(), [{ text: "部分的な回答", sender: "bot" }]);
});

test("a response with no body raises the localized stream failure", async () => {
  const clock = createFakeClock();
  const recorder = createStreamHostRecorder({ clock });
  const stream = createScriptedStream([], { bodyless: true });

  await assert.rejects(() => settleStream(consumeGenerationStream(stream.response, recorder.host), clock), {
    message: "ストリーム応答を受信できませんでした。",
  });
});

// ---------------------------------------------------------------------------
// 再接続とバックオフ / reconnect and backoff
// ---------------------------------------------------------------------------

test("repeated reconnect failures follow the capped backoff and keep local progress", async () => {
  const clock = createFakeClock();
  let attempts = 0;
  const resumed = createScriptedStream([sseBlock(2, "done", { response: "最終的な回答" })]);

  const recorder = createStreamHostRecorder({
    clock,
    openStream: () => {
      attempts += 1;
      // 最初の3回はネットワーク到達不可、4回目でつながる。
      // The first three attempts cannot reach the network; the fourth connects.
      if (attempts <= 3) return Promise.reject(new TypeError("Failed to fetch"));
      return Promise.resolve(resumed.response);
    },
  });
  seedThinkingMessage(recorder);

  const interrupted = createScriptedStream([sseBlock(1, "chunk", { text: "途中まで" })]);

  const completed = await settleStream(consumeGenerationStream(interrupted.response, recorder.host), clock);

  assert.equal(completed, true);
  assert.equal(attempts, 4);
  // バックオフ待ちが即時 → 500 → 1000 → 2000 の順で入る。
  // The backoff waits are 0, 500, 1000 and 2000 in that order.
  const backoffDelays = clock.recordedDelays.filter((delay) =>
    [0, 500, 1_000, 2_000, 4_000].includes(delay),
  );
  assert.deepEqual(backoffDelays.slice(0, 4), [0, 500, 1_000, 2_000]);
  assert.equal(assistantMessages(recorder.messages())[0].text, "最終的な回答");
  assert.deepEqual(recorder.errors(), []);
});

test("no reconnect is attempted when no event id was ever received", async () => {
  const clock = createFakeClock();
  let attempts = 0;

  const recorder = createStreamHostRecorder({
    clock,
    openStream: () => {
      attempts += 1;
      return Promise.reject(new Error("must not be called"));
    },
  });
  seedThinkingMessage(recorder);

  // イベントIDの無いチャンクだけを受けて切断する。
  // The stream drops after chunks that carry no event id.
  const interrupted = createScriptedStream([sseBlock(null, "chunk", { text: "IDなし" })]);

  const consuming = consumeGenerationStream(interrupted.response, recorder.host);
  await flushMicrotasks();
  for (let step = 0; step < 6; step += 1) {
    clock.runFrames();
    clock.advance(1_000);
    await flushMicrotasks();
  }

  assert.equal(attempts, 0);
  // 再接続不能でも進捗は残したまま、停止されるまで再試行を続ける。
  // With no resume point it keeps retrying, holding on to local progress.
  assert.equal(assistantMessages(recorder.messages()).length, 1);

  recorder.setActive(false);
  assert.equal(await settleStream(consuming, clock), false);
});

test("aborting during the reconnect wait ends the turn quietly", async () => {
  const clock = createFakeClock();
  let attempts = 0;
  const recorder = createStreamHostRecorder({
    clock,
    openStream: () => {
      attempts += 1;
      return Promise.reject(new Error("must not be called"));
    },
  });
  seedThinkingMessage(recorder);

  const interrupted = createScriptedStream([sseBlock(1, "chunk", { text: "途中まで" })]);
  const consuming = consumeGenerationStream(interrupted.response, recorder.host);

  await flushMicrotasks();
  recorder.setActive(false);
  recorder.abortController.abort();

  assert.equal(await settleStream(consuming, clock), false);
  assert.equal(attempts, 0);
  assert.deepEqual(recorder.errors(), []);
});

// 復元データがあるときは、その本文を即時表示してから続きを受ける。
// With a persisted draft, the restored text shows instantly before the rest arrives.
test("a persisted draft is restored and resumed from its last event id", async () => {
  const clock = createFakeClock();
  const recorder = createStreamHostRecorder({
    clock,
    storedGeneration: {
      roomId: "room-1",
      roomMode: "normal",
      lastEventId: 7,
      streamedText: "復元された本文",
      updatedAt: Date.now(),
    },
  });
  seedThinkingMessage(recorder);

  const stream = createScriptedStream([
    // 復元済みIDと同じ 7 は再送分なので取り込まれてはいけない。
    // Id 7 matches the restored id, so this replayed block must be ignored.
    sseBlock(7, "chunk", { text: "【再送】" }),
    sseBlock(8, "chunk", { text: "の続き" }),
    sseBlock(9, "done", { response: "復元された本文の続き" }),
  ]);

  const consuming = consumeGenerationStream(stream.response, recorder.host);
  await flushMicrotasks();

  // 復元テキストはリプレイせず、最初のフレームで全文が出る。
  // Restored text is not replayed: it is fully visible from the first frame.
  const restored = assistantMessages(recorder.messages())[0];
  assert.ok(restored.text.startsWith("復元された本文"), `restored text was ${restored.text}`);
  assert.ok(
    !restored.text.includes("【再送】"),
    "an event id at or below the restored id must not be applied again",
  );

  const completed = await settleStream(consuming, clock);
  assert.equal(completed, true);
  assert.equal(assistantMessages(recorder.messages())[0].text, "復元された本文の続き");
});

test("stream progress is written back to the persisted draft while chunks arrive", async () => {
  const clock: FakeClock = createFakeClock();
  const recorder = createStreamHostRecorder({
    clock,
    storedGeneration: {
      roomId: "room-1",
      roomMode: "normal",
      lastEventId: 0,
      streamedText: "",
      updatedAt: Date.now(),
    },
  });
  seedThinkingMessage(recorder);

  const interrupted = createScriptedStream([
    sseBlock(1, "chunk", { text: "保存されるべき" }),
    sseBlock(2, "chunk", { text: "本文" }),
  ]);

  const consuming = consumeGenerationStream(interrupted.response, recorder.host);
  await flushMicrotasks();
  // スロットル間隔(250ms)を超えて初めて書き込まれる。
  // The write only happens once the 250 ms throttle window has passed.
  clock.advance(300);
  await flushMicrotasks();

  const stored = recorder.storedGeneration();
  assert.equal(stored?.streamedText, "保存されるべき本文");
  assert.equal(stored?.lastEventId, 2);

  recorder.setActive(false);
  await settleStream(consuming, clock);
});
