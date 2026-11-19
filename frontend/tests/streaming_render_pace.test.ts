// 生成中の本文の描き直しを、かかった時間に応じて空ける間隔を検証する。
// Tests how long the streaming re-render waits given the cost of the previous render.

import assert from "node:assert/strict";
import test from "node:test";

import {
  MAX_STREAM_RENDER_GAP_MS,
  STREAM_RENDER_FREE_COST_MS,
  streamRenderGapMs,
} from "../lib/chat_page/streaming_render_pace";

test("streamRenderGapMs leaves cheap renders unspaced", () => {
  assert.equal(streamRenderGapMs(0), 0);
  assert.equal(streamRenderGapMs(STREAM_RENDER_FREE_COST_MS), 0);
});

test("streamRenderGapMs leaves the main thread free for as long as a heavy render took", () => {
  assert.equal(streamRenderGapMs(STREAM_RENDER_FREE_COST_MS + 1), STREAM_RENDER_FREE_COST_MS + 1);
  assert.equal(streamRenderGapMs(60), 60);
});

test("streamRenderGapMs never holds text back longer than the cap", () => {
  assert.equal(streamRenderGapMs(MAX_STREAM_RENDER_GAP_MS * 4), MAX_STREAM_RENDER_GAP_MS);
});

test("streamRenderGapMs treats an unusable cost as no gap", () => {
  assert.equal(streamRenderGapMs(Number.NaN), 0);
  assert.equal(streamRenderGapMs(-5), 0);
});
