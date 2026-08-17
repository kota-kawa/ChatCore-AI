import assert from "node:assert/strict";
import test from "node:test";

import { getInitialThinkingState } from "../lib/chat_page/thinking_status";

test("shows personal-knowledge lookup while selected references are prefetched", () => {
  assert.deepEqual(getInitialThinkingState(true, false, "ja"), {
    text: "メモとマイコンテキストを検索しています",
    generationPhase: "web-search",
  });
});

test("shows both selected lookup types when both are enabled", () => {
  assert.deepEqual(getInitialThinkingState(true, true, "ja"), {
    text: "メモ、マイコンテキスト、共有プロンプトを検索しています",
    generationPhase: "web-search",
  });
});

test("keeps the existing preparing status when no selected lookup is enabled", () => {
  assert.deepEqual(getInitialThinkingState(false, false, "en"), {
    text: "AI is preparing a response",
    generationPhase: "preparing",
  });
});
