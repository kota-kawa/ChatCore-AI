// チャットで自動保存された記憶の取得クライアントの正規化と失敗時の扱いを検証する。
// Tests the normalization and failure handling of the auto-saved memory client.

import assert from "node:assert/strict";
import test from "node:test";

import { fetchAutoSavedMemories, normalizeAutoSavedMemoryList } from "../lib/chat_page/auto_saved_memory_api";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

test("normalizeAutoSavedMemoryList maps facts to notices and keeps the enabled flag", () => {
  const result = normalizeAutoSavedMemoryList({
    enabled: true,
    facts: [{ id: 31, message_id: 55, title: "Rust", revision: 2, extra: "ignored" }],
  });
  assert.deepEqual(result, { enabled: true, memories: [{ id: 31, messageId: 55, title: "Rust", revision: 2 }] });
});

test("normalizeAutoSavedMemoryList reports a disabled setting and drops malformed items", () => {
  const result = normalizeAutoSavedMemoryList({
    enabled: false,
    facts: [{ id: "x", message_id: 1, title: "bad", revision: 1 }, { id: 2, message_id: 3, title: "ok", revision: 1 }],
  });
  assert.deepEqual(result, { enabled: false, memories: [{ id: 2, messageId: 3, title: "ok", revision: 1 }] });
});

test("normalizeAutoSavedMemoryList treats a missing enabled flag as disabled", () => {
  assert.equal(normalizeAutoSavedMemoryList({ facts: [] })?.enabled, false);
});

test("normalizeAutoSavedMemoryList returns null for an unreadable payload", () => {
  assert.equal(normalizeAutoSavedMemoryList(null), null);
  assert.equal(normalizeAutoSavedMemoryList({ enabled: true }), null);
  assert.equal(normalizeAutoSavedMemoryList("oops"), null);
});

test("fetchAutoSavedMemories sends the room id as an encoded query and parses the answer", async () => {
  const requested: string[] = [];
  const result = await fetchAutoSavedMemories("room a&b", async (input) => {
    requested.push(String(input));
    return jsonResponse({ enabled: true, facts: [{ id: 1, message_id: 9, title: "T", revision: 1 }] });
  });
  assert.equal(requested.length, 1);
  const parsed = new URL(requested[0], "https://example.com");
  assert.equal(parsed.pathname, "/api/context-facts/auto-saved");
  assert.equal(parsed.searchParams.get("room_id"), "room a&b");
  assert.equal(result?.memories[0]?.messageId, 9);
});

test("fetchAutoSavedMemories returns null for a failed response and lets network errors throw", async () => {
  assert.equal(await fetchAutoSavedMemories("r", async () => jsonResponse({ status: "fail" }, 401)), null);
  assert.equal(await fetchAutoSavedMemories("r", async () => jsonResponse({ status: "fail" }, 500)), null);
  await assert.rejects(
    fetchAutoSavedMemories("r", async () => {
      throw new TypeError("network down");
    }),
    TypeError,
  );
});
