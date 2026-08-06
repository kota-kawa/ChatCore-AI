import assert from "node:assert/strict";
import test, { afterEach, beforeEach } from "node:test";

import { forkSharedChat, rememberForkedChatRoom } from "../lib/shared_chat/fork_shared_chat";
import { readStoredActiveChatRoom, shouldRestoreHomeChatView } from "../lib/chat_page/storage";

const originalFetch = globalThis.fetch;

type FetchCall = { url: string; init: RequestInit | undefined };

function stubFetch(response: Response) {
  const calls: FetchCall[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), init });
    return response;
  }) as typeof fetch;
  return calls;
}

// localStorage を使うテスト用に最小限のスタブを用意する。
// Minimal localStorage stub for the tests that touch stored chat state.
function installLocalStorageStub() {
  const store = new Map<string, string>();
  const stub = {
    getItem: (key: string) => (store.has(key) ? store.get(key)! : null),
    setItem: (key: string, value: string) => {
      store.set(key, String(value));
    },
    removeItem: (key: string) => {
      store.delete(key);
    },
    clear: () => {
      store.clear();
    },
    key: (index: number) => Array.from(store.keys())[index] ?? null,
    get length() {
      return store.size;
    },
  };
  (globalThis as { localStorage?: unknown }).localStorage = stub;
}

beforeEach(() => {
  installLocalStorageStub();
});

afterEach(() => {
  globalThis.fetch = originalFetch;
});

test("forkSharedChat posts the token and returns the created room", async () => {
  const calls = stubFetch(
    new Response(JSON.stringify({ id: "room-9", title: "共有チャット", mode: "normal", message_count: 4 }), {
      status: 201,
      headers: { "content-type": "application/json" },
    }),
  );

  const room = await forkSharedChat("token-1", "room-9", "失敗しました");

  assert.deepEqual(room, { id: "room-9", mode: "normal" });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "/api/fork_shared_chat_room");
  assert.equal(calls[0].init?.method, "POST");
  assert.deepEqual(JSON.parse(String(calls[0].init?.body)), { token: "token-1", id: "room-9" });
});

test("forkSharedChat reports a temporary room for guests", async () => {
  stubFetch(
    new Response(JSON.stringify({ id: "room-9", mode: "temporary" }), {
      status: 201,
      headers: { "content-type": "application/json" },
    }),
  );

  assert.deepEqual(await forkSharedChat("token-1", "room-9", "失敗しました"), {
    id: "room-9",
    mode: "temporary",
  });
});

test("forkSharedChat surfaces the server error message", async () => {
  stubFetch(
    new Response(JSON.stringify({ error: "共有リンクが見つかりません" }), {
      status: 404,
      headers: { "content-type": "application/json" },
    }),
  );

  await assert.rejects(
    () => forkSharedChat("missing", "room-9", "失敗しました"),
    /共有リンクが見つかりません/,
  );
});

test("forkSharedChat fails when the response has no room id", async () => {
  stubFetch(
    new Response(JSON.stringify({ mode: "normal" }), {
      status: 201,
      headers: { "content-type": "application/json" },
    }),
  );

  await assert.rejects(() => forkSharedChat("token-1", "room-9", "失敗しました"), /失敗しました/);
});

test("rememberForkedChatRoom makes the fork the room the chat view restores", () => {
  rememberForkedChatRoom({ id: "room-9", mode: "temporary" });

  assert.deepEqual(readStoredActiveChatRoom(), { roomId: "room-9", roomMode: "temporary" });
  assert.equal(shouldRestoreHomeChatView(), true);
});
