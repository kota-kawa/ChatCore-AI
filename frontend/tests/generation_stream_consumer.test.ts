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
  return { ok: status >= 200 && status < 300, status, headers: {
    get: (name: string) => name.toLowerCase() === "content-type" ? "application/json" : null,
  } } as unknown as Response;
}

// 「思考中」だけが並んでいる初期状態を作る。
// Start from the state the hook leaves behind: a lone thinking placeholder.
function seedThinkingMessage(recorder: ReturnType<typeof createStreamHostRecorder>) {
  recorder.host.messages.updateActiveMessages(() => [
    { id: "thinking-0", sender: "thinking", text: "思考中", generationPhase: "preparing" },
  ]);
}

test("a second answer reconnects with its own generation id and a fresh event cursor", async () => {
  const clock = createFakeClock();
  const recorder = createStreamHostRecorder({
    clock,
    openStream: async (lastEventId, generationId) => {
      assert.equal(lastEventId, 1);
      assert.equal(generationId, "second-generation");
      return createScriptedStream([
        sseBlock(2, "done", { response: "2回目の回答" }),
      ], { generationId }).response;
    },
  });
  const first = createScriptedStream([
    sseBlock(1, "chunk", { text: "1回目の回答" }),
    sseBlock(2, "done", { response: "1回目の回答" }),
  ], { generationId: "first-generation" });
  await settleStream(consumeGenerationStream(first.response, recorder.host), clock);

  const second = createScriptedStream([
    sseBlock(1, "chunk", { text: "2回目の" }),
  ], { generationId: "second-generation" });
  assert.equal(await settleStream(consumeGenerationStream(second.response, recorder.host), clock), true);
  assert.deepEqual(assistantMessages(recorder.messages()).map((message) => message.text), ["1回目の回答", "2回目の回答"]);
});

test("a new generation discards the previous answer's stored draft and event ids", async () => {
  const clock = createFakeClock();
  const recorder = createStreamHostRecorder({
    clock,
    storedGeneration: {
      roomId: "room-1", roomMode: "normal", generationId: "old-generation",
      lastEventId: 99, streamedText: "前回の下書き", updatedAt: Date.now(),
    },
  });
  recorder.lastEventIds.set("room-1", 99);
  const stream = createScriptedStream([
    sseBlock(1, "chunk", { text: "今回の回答" }),
    sseBlock(2, "done", { response: "今回の回答" }),
  ], { generationId: "new-generation" });
  assert.equal(await settleStream(consumeGenerationStream(stream.response, recorder.host), clock), true);
  assert.deepEqual(assistantMessages(recorder.messages()).map((message) => message.text), ["今回の回答"]);
});

test("a reconnect for another generation never replaces the partial answer", async () => {
  const clock = createFakeClock();
  const recorder = createStreamHostRecorder({
    clock,
    openStream: async () => createScriptedStream([
      sseBlock(2, "done", { response: "前回の回答" }),
    ], { generationId: "wrong-generation" }).response,
  });
  const stream = createScriptedStream([
    sseBlock(1, "chunk", { text: "今回の途中回答" }),
  ], { generationId: "current-generation" });
  assert.equal(await settleStream(consumeGenerationStream(stream.response, recorder.host), clock), false);
  assert.equal(assistantMessages(recorder.messages())[0].text, "今回の途中回答");
  assert.equal(recorder.messages().some((message) => message.text.includes("前回の回答")), false);
});

test("an initial recovery response for another generation is rejected before rendering", () => {
  const recorder = createStreamHostRecorder({ clock: createFakeClock() });
  recorder.host.generationId = "requested-generation";
  const stream = createScriptedStream([
    sseBlock(1, "done", { response: "前回の回答" }),
  ], { generationId: "previous-generation" });
  assert.throws(() => consumeGenerationStream(stream.response, recorder.host), /別の回答/);
  assert.deepEqual(recorder.messages(), []);
  assert.deepEqual(recorder.persistedAnswers(), []);
});

test("a matching generation restores its draft and pins the reconnect", async () => {
  const clock = createFakeClock();
  const recorder = createStreamHostRecorder({
    clock,
    storedGeneration: {
      roomId: "room-1", roomMode: "normal", generationId: "current-generation",
      lastEventId: 7, streamedText: "復元された本文", updatedAt: Date.now(),
    },
    openStream: async (lastEventId, generationId) => {
      assert.equal(lastEventId, 8);
      assert.equal(generationId, "current-generation");
      return createScriptedStream([
        sseBlock(9, "done", { response: "復元された本文の続き" }),
      ], { generationId }).response;
    },
  });
  const stream = createScriptedStream([
    sseBlock(7, "chunk", { text: "再送は無視" }),
    sseBlock(8, "chunk", { text: "の続き" }),
  ], { generationId: "current-generation" });
  assert.equal(await settleStream(consumeGenerationStream(stream.response, recorder.host), clock), true);
  assert.deepEqual(assistantMessages(recorder.messages()).map((message) => message.text), ["復元された本文の続き"]);
});

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

// 仮想フレームを進めながら、上限時間までに決着するかを返す。settleStream と違い、
// 決着しなくても待ち続けない（退行時にテストが固まらない）。
// Drives virtual frames up to a time limit and reports whether the promise
// settled. Unlike settleStream it never waits forever, so a regression fails
// the assertion instead of hanging the test.
async function driveWithin<T>(promise: Promise<T>, clock: FakeClock, limitMs: number, withFrames = true) {
  let result: { value: T } | null = null;
  void promise.then((value) => {
    result = { value };
  });
  const startedAt = clock.now();
  while (!result && clock.now() - startedAt < limitMs) {
    await flushMicrotasks();
    if (withFrames) clock.runFrames();
    clock.advance(60);
    await flushMicrotasks();
  }
  return { settled: result !== null, value: (result as { value: T } | null)?.value, elapsedMs: clock.now() - startedAt };
}

// done を受けたら、長い回答でも短い時間で全文を出し切り、呼び出し側へ制御を返す。
// 通常の上限（120文字/秒）のままだと 20,000 文字で約 167 秒かかり、停止ボタンが
// 生成完了後もその間ずっと残っていた。
// After "done", even a very long answer is fully revealed within a short window
// and control returns to the caller. At the normal 120 chars/s cap, 20,000
// characters took about 167s, keeping the stop button up long after the
// generation was over.
test("a long answer finishes within about a second of done instead of trickling out", async () => {
  const clock = createFakeClock();
  const recorder = createStreamHostRecorder({ clock });
  seedThinkingMessage(recorder);

  const longAnswer = "あ".repeat(20_000);
  const stream = createScriptedStream([
    sseBlock(1, "chunk", { text: longAnswer }),
    sseBlock(2, "done", { response: longAnswer }),
  ]);

  // 早送り 600ms + 最後の語のフェード待ち 620ms + テストの刻み幅。
  // 600ms fast-forward + 620ms final-fade wait + the test's step granularity.
  const driven = await driveWithin(consumeGenerationStream(stream.response, recorder.host), clock, 1_400);

  assert.equal(driven.settled, true, "the stream must resolve within ~1.4s of done");
  assert.equal(driven.value, true);
  const answers = assistantMessages(recorder.messages());
  assert.equal(answers[0].text, longAnswer);
  assert.equal(answers[0].streaming, false);
  assert.deepEqual(recorder.persistedAnswers(), [{ text: longAnswer, sender: "bot" }]);
});

// 先頭のブロックを返したあと、release() が呼ばれるまで読み出しを止める。done を
// 「文字送りの途中で」届けるために使う。
// Serves the leading blocks, then holds the read until release() is called, so
// that "done" can arrive in the middle of a paced reveal.
function createGatedStream(leading: string[]) {
  const encoder = new TextEncoder();
  let index = 0;
  let release: (block: string) => void = () => undefined;
  const gate = new Promise<string>((resolve) => {
    release = resolve;
  });
  const reader = {
    read: async () => {
      if (index < leading.length) {
        index += 1;
        return { value: encoder.encode(leading[index - 1]), done: false };
      }
      if (index === leading.length) {
        index += 1;
        return { value: encoder.encode(await gate), done: false };
      }
      return { value: undefined, done: true };
    },
    cancel: async () => undefined,
  };
  const response = {
    ok: true,
    status: 200,
    headers: { get: (name: string) => name.toLowerCase() === "content-type" ? "text/event-stream" : null },
    body: { getReader: () => reader },
  } as unknown as Response;
  return { response, release };
}

// 通常の文字送りで途中まで進んだあとに done が来ても、done から一定時間で終わる。
// A done that lands mid-reveal still finishes within a fixed time from done.
test("done in the middle of a paced reveal fast-forwards the remainder", async () => {
  const clock = createFakeClock();
  const recorder = createStreamHostRecorder({ clock });
  seedThinkingMessage(recorder);

  const longAnswer = "これは途中で完了通知を受ける長い回答です。".repeat(500);
  const gated = createGatedStream([sseBlock(1, "chunk", { text: longAnswer })]);
  const consuming = consumeGenerationStream(gated.response, recorder.host);
  await flushMicrotasks();

  // done 前は通常の上限付き速度のまま（2秒で 240 文字以下）。
  // Before done the capped pace applies (at most 240 chars in 2 seconds).
  for (let elapsed = 0; elapsed < 2_000; elapsed += 16) {
    clock.runFrames();
    clock.advance(16);
  }
  clock.runFrames();
  const revealedBeforeDone = assistantMessages(recorder.messages())[0].text.length;
  assert.ok(revealedBeforeDone > 0 && revealedBeforeDone <= 240, `pre-done pace changed: ${revealedBeforeDone}`);

  gated.release(sseBlock(2, "done", { response: longAnswer }));
  const driven = await driveWithin(consuming, clock, 1_400);

  assert.equal(driven.settled, true, "the stream must resolve within ~1.4s of done");
  assert.equal(driven.value, true);
  assert.equal(assistantMessages(recorder.messages())[0].text, longAnswer);
  assert.equal(assistantMessages(recorder.messages())[0].streaming, false);
});

// rAF が止まる非表示タブでも、締め切りのタイマーで描画が進み完了する。
// In a hidden tab rAF is paused; the deadline timer still drives the finish.
test("a long answer still finishes after done when animation frames never fire", async () => {
  const clock = createFakeClock();
  const recorder = createStreamHostRecorder({ clock });
  seedThinkingMessage(recorder);

  const longAnswer = "い".repeat(20_000);
  const stream = createScriptedStream([
    sseBlock(1, "chunk", { text: longAnswer }),
    sseBlock(2, "done", { response: longAnswer }),
  ]);

  // フレームを進めない = rAF が一度も発火しない。
  // Not running frames means rAF never fires.
  const driven = await driveWithin(consumeGenerationStream(stream.response, recorder.host), clock, 2_000, false);

  assert.equal(driven.settled, true, "the deadline timer must finish the reveal without rAF");
  assert.equal(assistantMessages(recorder.messages())[0].text, longAnswer);
  assert.equal(assistantMessages(recorder.messages())[0].streaming, false);
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

// バグ1: 再開位置(lastEventId)が一度も届かないまま切断されると、以前は
// openReconnectStream が無条件に null を返し続け、再試行が永遠にループして
// エラーも生成ガードの解放も起きなかった。再開位置が無い切断は即座に
// 諦めるべきで、再接続(host.openStream)を試すだけ無駄である。
// Bug 1: dropping before a resume point (lastEventId) ever arrived used to
// make openReconnectStream return null forever, spinning the retry loop with
// no error and no release of the generation guard. A drop with no resume
// point should give up immediately; retrying host.openStream cannot help.
test("a drop with no event id ever received ends the turn instead of retrying forever", async () => {
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

  // イベントIDの無いチャンクだけを受けて切断する（ヘッダーだけ返して本文を
  // 送らないプロキシ／LB を模す）。
  // The stream drops after a chunk that carries no event id (mirrors a
  // proxy/LB that returns headers but sends no events before cutting off).
  const interrupted = createScriptedStream([sseBlock(null, "chunk", { text: "IDなし" })]);

  const completed = await settleStream(consumeGenerationStream(interrupted.response, recorder.host), clock);

  assert.equal(completed, false);
  // 再開位置が無いので、host.openStream は一度も呼ばれない。
  // With no resume point, host.openStream is never called.
  assert.equal(attempts, 0);
  // ユーザーの目に留まる形で、部分的な回答とエラーを一度だけ残す。
  // Surfaces visibly: the partial answer plus a single error, exactly once.
  const answers = assistantMessages(recorder.messages());
  assert.equal(answers.length, 2);
  assert.equal(answers[0].text, "IDなし");
  assert.equal(recorder.errors().length, 1);
  assert.match(recorder.errors()[0], /ストリームを再開できませんでした/);
});

// バグ1: lastEventId はあるが再接続そのものが繰り返し失敗するケース。
// 上限に達したら諦め、無限ループしないことを確認する。
// Bug 1: a resume point exists, but reconnecting itself keeps failing.
// Verify it gives up once the retry budget is exhausted instead of looping
// forever.
test("reconnect attempts stop after 12 CONSECUTIVE failures instead of spinning forever", async () => {
  const clock = createFakeClock();
  let attempts = 0;

  const recorder = createStreamHostRecorder({
    clock,
    openStream: () => {
      attempts += 1;
      return Promise.reject(new TypeError("Failed to fetch"));
    },
  });
  seedThinkingMessage(recorder);

  const interrupted = createScriptedStream([sseBlock(1, "chunk", { text: "途中まで" })]);

  // バックオフの合計は約105秒（0+500+1000+2000+4000+8000+15000*6ms）に及ぶため、
  // 既定の maxSteps では時間切れになる。
  // The cumulative backoff runs to roughly 105s (0+500+1000+2000+4000+8000+15000*6ms),
  // so the default maxSteps would time out before it settles.
  const completed = await settleStream(consumeGenerationStream(interrupted.response, recorder.host), clock, 3_000);

  assert.equal(completed, false);
  // 12回試して打ち切る（約105秒粘ってから諦める上限）。
  // Gives up after exactly 12 attempts (the ~105s retry budget).
  assert.equal(attempts, 12);
  assert.equal(recorder.errors().length, 1);
  assert.match(recorder.errors()[0], /ストリームを再開できませんでした/);
  assert.equal(assistantMessages(recorder.messages())[0]?.text, "途中まで");
});

// 再接続が 200 で開いても、イベントを1件も届けずに閉じるなら成功ではない。
// 成功扱いで試行回数を 0 に戻すと、待ち 0ms のまま無限に再接続してしまう。
// A reconnect that opens with a 200 but closes without delivering a single
// event is not a success. Resetting the attempt count on it would reconnect
// forever at a 0ms wait.
test("reconnects that open with 200 but deliver no event count as failures and give up at the cap", async () => {
  const clock = createFakeClock();
  let attempts = 0;

  const recorder = createStreamHostRecorder({
    clock,
    openStream: () => {
      attempts += 1;
      // 退行時に無限ループでテストが固まらないよう、30回を超えたら通常の失敗に切り替える。
      // Switch to ordinary failures after 30 calls so a regression ends the test instead of hanging it.
      if (attempts > 30) return Promise.reject(new TypeError("Failed to fetch"));
      return Promise.resolve(createScriptedStream([]).response);
    },
  });
  seedThinkingMessage(recorder);

  const interrupted = createScriptedStream([sseBlock(1, "chunk", { text: "途中まで" })]);

  const completed = await settleStream(consumeGenerationStream(interrupted.response, recorder.host), clock, 3_000);

  assert.equal(completed, false);
  assert.equal(attempts, 12);
  assert.equal(recorder.errors().length, 1);
  assert.match(recorder.errors()[0], /ストリームを再開できませんでした/);
  assert.equal(assistantMessages(recorder.messages())[0]?.text, "途中まで");
});

// レビュー指摘: 再接続上限は「生涯合計」ではなく「連続失敗」に対する予算で
// なければならない。11回連続で再接続に成功した後にたった1回失敗しても、
// そこで打ち切ってはいけない（1回失敗しても次で回復すれば良い）。
// Review finding: the reconnect budget must cap consecutive failures, not a
// lifetime total. Eleven consecutive successful reconnects followed by a
// single failure must not cut the turn off (it should simply try again).
test("many successful reconnects followed by a single failure do not cut the turn off", async () => {
  const clock = createFakeClock();
  let openStreamCalls = 0;

  const recorder = createStreamHostRecorder({
    clock,
    openStream: () => {
      openStreamCalls += 1;
      const eventId = openStreamCalls + 1;
      if (openStreamCalls === 12) {
        // 12回目だけ失敗させる。生涯合計で数えていると、11回の成功を経ても
        // ここでちょうど上限(12)に達して打ち切られてしまう。
        // Only the 12th call fails. Counting a lifetime total would make this
        // land exactly on the cap (12) despite 11 prior successes.
        return Promise.reject(new TypeError("Failed to fetch"));
      }
      if (openStreamCalls === 13) {
        return Promise.resolve(createScriptedStream([sseBlock(eventId, "done", { response: "最終回答" })]).response);
      }
      // 毎回1チャンク届けてすぐ切断し、次の再接続を促す。
      // Deliver one chunk each time, then disconnect to prompt another reconnect.
      return Promise.resolve(
        createScriptedStream([sseBlock(eventId, "chunk", { text: `chunk-${openStreamCalls}` })]).response,
      );
    },
  });
  seedThinkingMessage(recorder);

  const interrupted = createScriptedStream([sseBlock(1, "chunk", { text: "開始" })]);

  const completed = await settleStream(consumeGenerationStream(interrupted.response, recorder.host), clock, 3_000);

  assert.equal(completed, true);
  assert.equal(openStreamCalls, 13);
  assert.deepEqual(recorder.errors(), []);
  assert.equal(assistantMessages(recorder.messages())[0].text, "最終回答");
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

// 送り込んだブロックだけを順に読ませるストリーム。途中の画面を見たいテストが、イベントの
// 到着をひとつずつ制御するために使う。
// A stream that yields only the blocks pushed into it, so a test can control event arrival one
// step at a time and inspect the screen in between.
function createControlledStream() {
  const encoder = new TextEncoder();
  const queue: string[] = [];
  let waiting: ((result: { value?: Uint8Array; done: boolean }) => void) | null = null;
  let closed = false;
  const reader = {
    read: () =>
      new Promise<{ value?: Uint8Array; done: boolean }>((resolve) => {
        if (queue.length > 0) {
          resolve({ value: encoder.encode(queue.shift()), done: false });
        } else if (closed) {
          resolve({ value: undefined, done: true });
        } else {
          waiting = resolve;
        }
      }),
    cancel: async () => undefined,
  };
  const response = {
    ok: true,
    status: 200,
    headers: { get: (name: string) => (name.toLowerCase() === "content-type" ? "text/event-stream" : null) },
    body: { getReader: () => reader, cancel: reader.cancel },
  } as unknown as Response;
  return {
    response,
    push(...blocks: string[]) {
      blocks.forEach((block) => {
        if (waiting) {
          const resolve = waiting;
          waiting = null;
          resolve({ value: encoder.encode(block), done: false });
        } else {
          queue.push(block);
        }
      });
    },
    close() {
      closed = true;
      if (waiting) {
        const resolve = waiting;
        waiting = null;
        resolve({ value: undefined, done: true });
      }
    },
  };
}

// 描画を数フレーム進めて、表示ペースの上限に邪魔されず本文が出た状態にする。
// Run enough frames for the paced reveal to show the text.
async function showFrames(clock: FakeClock, frames = 40) {
  for (let frame = 0; frame < frames; frame += 1) {
    await flushMicrotasks();
    clock.runFrames();
    clock.advance(30);
  }
  await flushMicrotasks();
}

const DRAFT_TEXT = "確定前に先行して見せる下書きの本文です。";

test("a draft is shown ahead of confirmation but never stored or counted as confirmed text", async () => {
  const clock = createFakeClock();
  const recorder = createStreamHostRecorder({
    clock,
    storedGeneration: { roomId: "room-1", roomMode: "normal", lastEventId: 0, streamedText: "", updatedAt: Date.now() },
  });
  seedThinkingMessage(recorder);
  const stream = createControlledStream();

  const consuming = consumeGenerationStream(stream.response, recorder.host);
  stream.push(sseBlock(1, "response_generation_started", {}), sseBlock(2, "answer_draft", { text: DRAFT_TEXT }));
  await showFrames(clock);

  const shown = assistantMessages(recorder.messages());
  assert.equal(shown.length, 1);
  assert.equal(shown[0].text, DRAFT_TEXT);
  assert.equal(shown[0].streaming, true);
  assert.equal(recorder.messages().some((message) => message.sender === "thinking"), false);
  // 復元データには下書きを入れない。再開位置も下書きのイベントでは進めない。
  // Recovery data holds no draft, and a draft event does not advance the resume position.
  clock.advance(400);
  assert.equal(recorder.storedGeneration()?.streamedText, "");
  assert.equal(recorder.storedGeneration()?.lastEventId, 1);

  stream.push(
    sseBlock(3, "answer_draft_reset", {}),
    sseBlock(4, "chunk", { text: DRAFT_TEXT }),
    sseBlock(5, "done", { response: DRAFT_TEXT }),
  );
  stream.close();
  const completed = await settleStream(consuming, clock);

  assert.equal(completed, true);
  const answers = assistantMessages(recorder.messages());
  assert.equal(answers.length, 1);
  assert.equal(answers[0].text, DRAFT_TEXT);
  assert.equal(answers[0].streaming, false);
  assert.deepEqual(recorder.persistedAnswers(), [{ text: DRAFT_TEXT, sender: "bot" }]);
});

test("draft deltas accumulate, and a reset followed by confirmed text keeps one bubble without duplicating", async () => {
  const clock = createFakeClock();
  const recorder = createStreamHostRecorder({ clock });
  seedThinkingMessage(recorder);
  const stream = createControlledStream();

  const consuming = consumeGenerationStream(stream.response, recorder.host);
  stream.push(sseBlock(1, "answer_draft", { text: "下書きの前半、" }), sseBlock(2, "answer_draft", { text: "下書きの後半です。" }));
  await showFrames(clock);
  const draftBubbleId = assistantMessages(recorder.messages())[0].id;
  assert.equal(assistantMessages(recorder.messages())[0].text, "下書きの前半、下書きの後半です。");

  stream.push(sseBlock(3, "answer_draft_reset", {}), sseBlock(4, "chunk", { text: "確定した本文です。" }));
  await showFrames(clock);

  const answers = assistantMessages(recorder.messages());
  assert.equal(answers.length, 1);
  assert.equal(answers[0].id, draftBubbleId);
  assert.equal(answers[0].text, "確定した本文です。");

  stream.push(sseBlock(5, "done", { response: "確定した本文です。" }));
  stream.close();
  await settleStream(consuming, clock);
  assert.deepEqual(recorder.persistedAnswers(), [{ text: "確定した本文です。", sender: "bot" }]);
});

test("a discarded draft that is followed by a tool call returns to the thinking indicator", async () => {
  const clock = createFakeClock();
  const recorder = createStreamHostRecorder({ clock });
  seedThinkingMessage(recorder);
  const stream = createControlledStream();

  const consuming = consumeGenerationStream(stream.response, recorder.host);
  stream.push(sseBlock(1, "answer_draft", { text: DRAFT_TEXT }));
  await showFrames(clock);
  assert.equal(assistantMessages(recorder.messages()).length, 1);

  stream.push(sseBlock(2, "answer_draft_reset", {}), sseBlock(3, "web_search_started", {}));
  await showFrames(clock);

  assert.equal(assistantMessages(recorder.messages()).length, 0);
  const thinking = recorder.messages().filter((message) => message.sender === "thinking");
  assert.equal(thinking.length, 1);
  assert.equal(thinking[0].generationPhase, "web-search");

  stream.push(sseBlock(4, "chunk", { text: "検索後の回答です。" }), sseBlock(5, "done", { response: "検索後の回答です。" }));
  stream.close();
  await settleStream(consuming, clock);
  assert.deepEqual(recorder.persistedAnswers(), [{ text: "検索後の回答です。", sender: "bot" }]);
  assert.equal(assistantMessages(recorder.messages()).length, 1);
});

test("a discard with no follow-up still returns to the thinking indicator on the next frame", async () => {
  const clock = createFakeClock();
  const recorder = createStreamHostRecorder({ clock });
  seedThinkingMessage(recorder);
  const stream = createControlledStream();

  const consuming = consumeGenerationStream(stream.response, recorder.host);
  stream.push(sseBlock(1, "answer_draft", { text: DRAFT_TEXT }), sseBlock(2, "answer_draft_reset", {}));
  await showFrames(clock);

  assert.equal(assistantMessages(recorder.messages()).length, 0);
  assert.equal(recorder.messages().filter((message) => message.sender === "thinking").length, 1);

  recorder.setActive(false);
  stream.close();
  await settleStream(consuming, clock);
});

test("an aborted event with no saved text removes the draft instead of keeping it", async () => {
  const clock = createFakeClock();
  const recorder = createStreamHostRecorder({ clock });
  seedThinkingMessage(recorder);
  const stream = createControlledStream();

  const consuming = consumeGenerationStream(stream.response, recorder.host);
  stream.push(sseBlock(1, "answer_draft", { text: DRAFT_TEXT }));
  await showFrames(clock);

  stream.push(sseBlock(2, "aborted", {}));
  stream.close();
  const completed = await settleStream(consuming, clock);

  assert.equal(completed, true);
  assert.equal(assistantMessages(recorder.messages()).length, 0);
  assert.equal(recorder.messages().some((message) => message.text.includes(DRAFT_TEXT)), false);
  assert.deepEqual(recorder.persistedAnswers(), []);
});

test("a stream error with only a draft shown hands the unanswered turn back without keeping the draft", async () => {
  const clock = createFakeClock();
  const recorder = createStreamHostRecorder({ clock, withUnansweredFailureHandler: true });
  seedThinkingMessage(recorder);
  const stream = createControlledStream();

  const consuming = consumeGenerationStream(stream.response, recorder.host);
  stream.push(sseBlock(1, "answer_draft", { text: DRAFT_TEXT }));
  await showFrames(clock);

  stream.push(sseBlock(2, "error", { message: "生成に失敗しました。" }));
  stream.close();
  const completed = await settleStream(consuming, clock);

  assert.equal(completed, false);
  assert.equal(recorder.unansweredFailures().length, 1);
  assert.equal(recorder.messages().some((message) => message.text.includes(DRAFT_TEXT)), false);
  assert.deepEqual(recorder.persistedAnswers(), []);
});

test("an incomplete event replaces the draft with the text the server saved", async () => {
  const clock = createFakeClock();
  const recorder = createStreamHostRecorder({ clock });
  seedThinkingMessage(recorder);
  const stream = createControlledStream();

  const consuming = consumeGenerationStream(stream.response, recorder.host);
  stream.push(sseBlock(1, "answer_draft", { text: DRAFT_TEXT }));
  await showFrames(clock);

  stream.push(
    sseBlock(2, "answer_draft_reset", {}),
    sseBlock(3, "chunk", { text: "保存された部分" }),
    sseBlock(4, "incomplete", { response: "保存された部分", message: "途中で終了しました。" }),
  );
  stream.close();
  await settleStream(consuming, clock);

  const answers = assistantMessages(recorder.messages()).filter((message) => !message.error);
  assert.equal(answers.length, 1);
  assert.equal(answers[0].text, "保存された部分");
  assert.equal(answers[0].partial, true);
});

test("a second connection sharing the room's resume position rebuilds the draft from its start", async () => {
  const clock = createFakeClock();
  const first = createStreamHostRecorder({ clock });
  seedThinkingMessage(first);
  const firstStream = createControlledStream();

  const firstConsuming = consumeGenerationStream(firstStream.response, first.host);
  firstStream.push(
    sseBlock(1, "response_generation_started", {}),
    sseBlock(2, "answer_draft", { text: "下書きの前半、" }),
    sseBlock(3, "answer_draft", { text: "下書きの後半です。" }),
  );
  await showFrames(clock);
  // 下書きのイベントは、ルームをまたぐ再開位置を進めない。
  // Draft events do not advance the per-room resume position.
  assert.equal(first.lastEventIds.get("room-1"), 1);

  // ルームを切り替えて戻った相当: 同じ再開位置の表を持つ新しい接続が、再生されたイベントを受ける。
  // Switching rooms and back: a new connection with the same resume table receives the replay.
  first.setActive(false);
  firstStream.close();
  await settleStream(firstConsuming, clock);

  const second = createStreamHostRecorder({ clock });
  const secondHost = { ...second.host, lastEventIdByRoom: first.lastEventIds };
  seedThinkingMessage(second);
  const secondStream = createControlledStream();
  const secondConsuming = consumeGenerationStream(secondStream.response, secondHost);
  secondStream.push(
    sseBlock(2, "answer_draft", { text: "下書きの前半、" }),
    sseBlock(3, "answer_draft", { text: "下書きの後半です。" }),
  );
  await showFrames(clock);

  assert.equal(assistantMessages(second.messages())[0].text, "下書きの前半、下書きの後半です。");

  secondStream.push(
    sseBlock(4, "answer_draft_reset", {}),
    sseBlock(5, "chunk", { text: "確定した本文です。" }),
    sseBlock(6, "done", { response: "確定した本文です。" }),
  );
  secondStream.close();
  await settleStream(secondConsuming, clock);
  assert.deepEqual(second.persistedAnswers(), [{ text: "確定した本文です。", sender: "bot" }]);
});

test("a reconnect replays the draft from the last non-draft event without duplicating it", async () => {
  const clock = createFakeClock();
  const replay = createControlledStream();
  const requestedFrom: number[] = [];
  const recorder = createStreamHostRecorder({
    clock,
    openStream: async (lastEventId) => {
      requestedFrom.push(lastEventId);
      return replay.response;
    },
  });
  seedThinkingMessage(recorder);
  const firstStream = createControlledStream();

  const consuming = consumeGenerationStream(firstStream.response, recorder.host);
  firstStream.push(
    sseBlock(1, "response_generation_started", {}),
    sseBlock(2, "answer_draft", { text: "下書きの前半、" }),
    sseBlock(3, "answer_draft", { text: "下書きの後半です。" }),
  );
  await showFrames(clock);
  firstStream.close();
  replay.push(
    sseBlock(2, "answer_draft", { text: "下書きの前半、" }),
    sseBlock(3, "answer_draft", { text: "下書きの後半です。" }),
  );
  await showFrames(clock, 120);

  assert.deepEqual(requestedFrom, [1]);
  assert.equal(assistantMessages(recorder.messages())[0].text, "下書きの前半、下書きの後半です。");

  replay.push(
    sseBlock(4, "answer_draft_reset", {}),
    sseBlock(5, "chunk", { text: "確定した本文です。" }),
    sseBlock(6, "done", { response: "確定した本文です。" }),
  );
  replay.close();
  const completed = await settleStream(consuming, clock);
  assert.equal(completed, true);
  assert.deepEqual(recorder.persistedAnswers(), [{ text: "確定した本文です。", sender: "bot" }]);
});
