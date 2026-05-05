import assert from "node:assert/strict";
import test from "node:test";

import {
  buildAiAgentHttpError,
  isSafeInternalPath,
  parseSseBlock,
} from "../lib/chat_page/ai_agent";

test("parseSseBlock parses named events with JSON data", () => {
  const event = parseSseBlock("event: progress\ndata: {\"message\":\"確認中\"}\n");

  assert.deepEqual(event, {
    type: "progress",
    message: "確認中",
  });
});

test("isSafeInternalPath rejects external navigation forms", () => {
  assert.equal(isSafeInternalPath("/settings"), true);
  assert.equal(isSafeInternalPath("//example.com"), false);
  assert.equal(isSafeInternalPath("/https://example.com"), false);
  assert.equal(isSafeInternalPath("https://example.com"), false);
});

test("buildAiAgentHttpError prefers server error message and retry_after", async () => {
  const response = new Response(
    JSON.stringify({ error: "上限に達しました。", retry_after: 30 }),
    { status: 429, headers: { "Content-Type": "application/json" } },
  );

  const error = await buildAiAgentHttpError(response);

  assert.equal(error.message, "上限に達しました。 30秒ほど待ってから再試行してください。");
});
