import assert from "node:assert/strict";
import test from "node:test";

import {
  appendStoredHistory,
  clearAllHomePagePersistedState,
  clearStoredGenerationState,
  prependStoredHistory,
  reconcileStoredUserScope,
  removeStoredHistory,
  readStoredActiveChatRoom,
  readActiveStoredGenerationState,
  readRestorableHomePageViewState,
  readStoredGenerationState,
  readStoredHistory,
  readStoredUserScope,
  writeStoredActiveChatRoom,
  writeStoredHomePageViewState,
  writeStoredGenerationState,
  writeStoredHistory,
} from "../lib/chat_page/storage";
import { __test__ as historyCacheTestConstants } from "../lib/chat_page/history_cache";
import type { StoredHistoryEntry } from "../lib/chat_page/types";
import { STORAGE_KEYS } from "../scripts/core/constants";

class FakeLocalStorage implements Storage {
  private readonly values = new Map<string, string>();
  quotaLimit: number | null = null;
  totalQuotaLimit: number | null = null;
  alwaysThrow = false;

  get length() {
    return this.values.size;
  }

  clear() {
    this.values.clear();
  }

  getItem(key: string) {
    return this.values.get(key) ?? null;
  }

  key(index: number) {
    return Array.from(this.values.keys())[index] ?? null;
  }

  removeItem(key: string) {
    this.values.delete(key);
  }

  setItem(key: string, value: string) {
    const totalLength = Array.from(this.values.entries()).reduce(
      (total, [storedKey, storedValue]) => total + (storedKey === key ? 0 : storedValue.length),
      value.length,
    );
    if (
      this.alwaysThrow
      || (this.quotaLimit !== null && value.length > this.quotaLimit)
      || (this.totalQuotaLimit !== null && totalLength > this.totalQuotaLimit)
    ) {
      throw new DOMException("Storage quota exceeded", "QuotaExceededError");
    }
    this.values.set(key, value);
  }

  get totalLength() {
    return Array.from(this.values.values()).reduce((total, value) => total + value.length, 0);
  }
}

function installFakeLocalStorage(storage: FakeLocalStorage) {
  Object.defineProperty(globalThis, "localStorage", {
    value: storage,
    configurable: true,
  });
}

test("writeStoredHistory reports a successful full write", () => {
  const storage = new FakeLocalStorage();
  installFakeLocalStorage(storage);

  const result = writeStoredHistory("room-a", [{ text: "hello", sender: "user" }]);

  assert.deepEqual(result, {
    stored: true,
    truncated: false,
    retainedEntries: 1,
    droppedEntries: 0,
  });
  assert.deepEqual(readStoredHistory("room-a"), [{ text: "hello", sender: "user" }]);
});

test("writeStoredHistory reports quota truncation and keeps newest messages", () => {
  const storage = new FakeLocalStorage();
  installFakeLocalStorage(storage);

  const entries: StoredHistoryEntry[] = Array.from({ length: 8 }, (_, index) => ({
    text: `message-${index}`,
    sender: index % 2 === 0 ? "user" : "bot",
  }));
  storage.quotaLimit = JSON.stringify(entries.slice(4)).length;

  const result = writeStoredHistory("room-b", entries);
  const retained = readStoredHistory("room-b");

  assert.equal(result.stored, true);
  assert.equal(result.truncated, true);
  assert.equal(result.reason, "quota_exceeded");
  assert.equal(result.retainedEntries, retained.length);
  assert.equal(result.droppedEntries, entries.length - retained.length);
  assert.ok(retained.length < entries.length);
  assert.equal(retained[retained.length - 1]?.text, "message-7");
});

test("writeStoredHistory silently bounds an oversized room cache", () => {
  const storage = new FakeLocalStorage();
  installFakeLocalStorage(storage);
  const entries: StoredHistoryEntry[] = Array.from({ length: 12 }, (_, index) => ({
    text: `${index}-${"x".repeat(60_000)}`,
    sender: index % 2 === 0 ? "user" : "bot",
  }));

  const result = writeStoredHistory("room-large", entries);
  const retained = readStoredHistory("room-large");

  assert.equal(result.stored, true);
  assert.equal(result.truncated, true);
  assert.equal(result.reason, "cache_limit");
  assert.ok(storage.getItem("chatHistory_room-large")!.length * 2 <= historyCacheTestConstants.MAX_HISTORY_ROOM_BYTES);
  assert.equal(retained.at(-1)?.text, entries.at(-1)?.text);
});

test("writeStoredHistory evicts the oldest rooms beyond the cache count", () => {
  const storage = new FakeLocalStorage();
  installFakeLocalStorage(storage);

  for (let index = 0; index <= historyCacheTestConstants.MAX_CACHED_HISTORY_ROOMS; index += 1) {
    writeStoredHistory(`room-${index}`, [{ text: `message-${index}`, sender: "user" }]);
  }

  assert.equal(storage.getItem("chatHistory_room-0"), null);
  assert.notEqual(
    storage.getItem(`chatHistory_room-${historyCacheTestConstants.MAX_CACHED_HISTORY_ROOMS}`),
    null,
  );
});

test("writeStoredHistory evicts another room before truncating on total quota", () => {
  const storage = new FakeLocalStorage();
  installFakeLocalStorage(storage);
  writeStoredHistory("room-old", [{ text: "x".repeat(2_000), sender: "user" }]);
  storage.setItem("unrelated-cache", "y".repeat(2_000));
  storage.totalQuotaLimit = storage.totalLength;

  const result = writeStoredHistory("room-new", [{ text: "latest", sender: "user" }]);

  assert.equal(result.stored, true);
  assert.equal(result.truncated, false);
  assert.equal(storage.getItem("chatHistory_room-old"), null);
  assert.notEqual(storage.getItem("chatHistory_room-new"), null);
});

test("appendStoredHistory reports an unpersisted quota failure", () => {
  const storage = new FakeLocalStorage();
  storage.alwaysThrow = true;
  installFakeLocalStorage(storage);

  const result = appendStoredHistory("room-c", { text: "unsaved", sender: "user" });

  assert.equal(result.stored, false);
  assert.equal(result.truncated, false);
  assert.equal(result.reason, "quota_exceeded");
  assert.equal(result.retainedEntries, 0);
  assert.equal(result.droppedEntries, 1);
});

test("stored generation state can be restored as the active generation", () => {
  const storage = new FakeLocalStorage();
  installFakeLocalStorage(storage);

  const stored = writeStoredGenerationState({
    roomId: "room-stream",
    roomMode: "normal",
    lastEventId: 12,
    streamedText: "途中まで",
    updatedAt: Date.now(),
  });

  assert.equal(stored, true);
  const restored = readStoredGenerationState("room-stream");
  assert.equal(restored?.roomId, "room-stream");
  assert.equal(restored?.roomMode, "normal");
  assert.equal(restored?.lastEventId, 12);
  assert.equal(restored?.streamedText, "途中まで");
  assert.equal(typeof restored?.updatedAt, "number");
  assert.equal(readActiveStoredGenerationState()?.roomId, "room-stream");
});

test("clearing stored generation state removes active generation pointer", () => {
  const storage = new FakeLocalStorage();
  installFakeLocalStorage(storage);

  writeStoredGenerationState({
    roomId: "room-clear",
    roomMode: "normal",
    lastEventId: 2,
    streamedText: "hello",
    updatedAt: Date.now(),
  });
  clearStoredGenerationState("room-clear");

  assert.equal(readStoredGenerationState("room-clear"), null);
  assert.equal(readActiveStoredGenerationState(), null);
});

test("removing stored history clears the room history and generation state", () => {
  const storage = new FakeLocalStorage();
  installFakeLocalStorage(storage);
  writeStoredHistory("room-delete", [{ text: "cached", sender: "user" }]);
  writeStoredGenerationState({
    roomId: "room-delete",
    roomMode: "normal",
    lastEventId: 3,
    streamedText: "partial",
    updatedAt: Date.now(),
  });

  removeStoredHistory("room-delete");

  assert.equal(storage.getItem("chatHistory_room-delete"), null);
  assert.equal(readStoredGenerationState("room-delete"), null);
  assert.equal(readActiveStoredGenerationState(), null);
});

test("home page view state persists setup and chat views", () => {
  const storage = new FakeLocalStorage();
  installFakeLocalStorage(storage);

  assert.equal(readRestorableHomePageViewState(), "setup");

  assert.equal(writeStoredHomePageViewState("launching"), true);
  assert.equal(storage.getItem(STORAGE_KEYS.homePageViewState), "chat");
  assert.equal(readRestorableHomePageViewState(), "chat");

  assert.equal(writeStoredHomePageViewState("setup"), true);
  assert.equal(storage.getItem(STORAGE_KEYS.homePageViewState), "setup");
  assert.equal(readRestorableHomePageViewState(), "setup");
});

test("restorable home page view returns chat while a generation is active", () => {
  const storage = new FakeLocalStorage();
  installFakeLocalStorage(storage);

  writeStoredGenerationState({
    roomId: "room-active-generation",
    roomMode: "normal",
    lastEventId: 4,
    streamedText: "応答中",
    updatedAt: Date.now(),
  });

  assert.equal(storage.getItem(STORAGE_KEYS.homePageViewState), null);
  assert.equal(readRestorableHomePageViewState(), "chat");
});

test("restorable home page view ignores stale active generation state", () => {
  const storage = new FakeLocalStorage();
  installFakeLocalStorage(storage);
  const staleGeneration = {
    roomId: "room-stale-generation",
    roomMode: "normal",
    lastEventId: 4,
    streamedText: "古い応答",
    updatedAt: Date.now() - 31 * 60 * 1000,
  };

  storage.setItem(STORAGE_KEYS.activeChatGeneration, JSON.stringify(staleGeneration));
  storage.setItem("chatGeneration_room-stale-generation", JSON.stringify(staleGeneration));

  assert.equal(readRestorableHomePageViewState(), "setup");
  assert.equal(readActiveStoredGenerationState(), null);
});

test("active chat room storage keeps temporary rooms out of legacy current room key", () => {
  const storage = new FakeLocalStorage();
  installFakeLocalStorage(storage);

  assert.equal(writeStoredActiveChatRoom("temp-room", "temporary"), true);
  assert.deepEqual(readStoredActiveChatRoom(), {
    roomId: "temp-room",
    roomMode: "temporary",
  });
  assert.equal(storage.getItem(STORAGE_KEYS.currentChatRoomId), null);

  assert.equal(writeStoredActiveChatRoom("normal-room", "normal"), true);
  assert.deepEqual(readStoredActiveChatRoom(), {
    roomId: "normal-room",
    roomMode: "normal",
  });
  assert.equal(storage.getItem(STORAGE_KEYS.currentChatRoomId), "normal-room");

  assert.equal(writeStoredActiveChatRoom(null), true);
  assert.equal(readStoredActiveChatRoom(), null);
  assert.equal(storage.getItem(STORAGE_KEYS.currentChatRoomId), null);
});

test("active chat room storage falls back to legacy current room id", () => {
  const storage = new FakeLocalStorage();
  installFakeLocalStorage(storage);
  storage.setItem(STORAGE_KEYS.currentChatRoomId, "legacy-room");

  assert.deepEqual(readStoredActiveChatRoom(), {
    roomId: "legacy-room",
    roomMode: "normal",
  });
});

test("readStoredHistory restores generated UI parts instead of dropping them", () => {
  // 保存時には parts を書いているのに読み戻しで捨てていたため、リロードすると
  // Artifact が本文だけの吹き出しに退化していた。
  // Parts were written on save but dropped on read, so a reload collapsed an artifact into a
  // text-only bubble.
  installFakeLocalStorage(new FakeLocalStorage());

  const artifact = {
    version: 1 as const,
    title: "比較マップ",
    html: '<div id="app"></div>',
    css: "#app{padding:12px}",
    js: "document.getElementById('app').textContent='ready';",
  };
  writeStoredHistory("room-parts", [
    {
      text: "作成しました。",
      sender: "bot",
      parts: [
        { type: "text", text: "作成しました。" },
        { type: "sandbox_artifact", artifact },
      ],
    },
  ]);

  const [entry] = readStoredHistory("room-parts");

  assert.equal(entry.parts?.length, 2);
  assert.equal(entry.parts?.[1].type, "sandbox_artifact");
});

test("readStoredHistory keeps a generated UI failure notice on reload", () => {
  installFakeLocalStorage(new FakeLocalStorage());

  writeStoredHistory("room-status", [
    {
      text: "比較結果はA案が優位です。",
      sender: "bot",
      parts: [
        { type: "text", text: "比較結果はA案が優位です。" },
        { type: "artifact_status", status: { state: "rejected", reasonCode: "required_artifact_missing" } },
      ],
    },
  ]);

  const [entry] = readStoredHistory("room-status");

  assert.deepEqual(entry.parts?.[1], {
    type: "artifact_status",
    status: { state: "rejected", reasonCode: "required_artifact_missing" },
  });
});

test("temporary rooms never persist history, and drop any pre-existing cache", () => {
  installFakeLocalStorage(new FakeLocalStorage());

  // 保存済みの本文が残っている状態から一時チャットに切り替わったケースも想定する。
  // Also cover switching to a temporary room while old cached text still exists.
  writeStoredHistory("room-temp", [{ text: "before", sender: "user" }]);

  const writeResult = writeStoredHistory("room-temp", [{ text: "leaked?", sender: "bot" }], "temporary");
  assert.equal(writeResult.stored, true);
  assert.deepEqual(readStoredHistory("room-temp"), []);

  const appendResult = appendStoredHistory("room-temp", { text: "leaked?", sender: "user" }, "temporary");
  assert.equal(appendResult.stored, true);
  assert.deepEqual(readStoredHistory("room-temp"), []);

  const prependResult = prependStoredHistory("room-temp", [{ text: "leaked?", sender: "bot" }], "temporary");
  assert.equal(prependResult.stored, true);
  assert.deepEqual(readStoredHistory("room-temp"), []);
});

test("temporary rooms never persist in-flight generation state", () => {
  installFakeLocalStorage(new FakeLocalStorage());

  const stored = writeStoredGenerationState({
    roomId: "room-temp",
    roomMode: "temporary",
    lastEventId: 3,
    streamedText: "leaked partial answer",
    updatedAt: Date.now(),
  });

  assert.equal(stored, true);
  assert.equal(readStoredGenerationState("room-temp"), null);
  assert.equal(readActiveStoredGenerationState(), null);
});

test("normal rooms are unaffected by the temporary-room guard", () => {
  installFakeLocalStorage(new FakeLocalStorage());

  writeStoredHistory("room-normal", [{ text: "kept", sender: "user" }], "normal");
  assert.deepEqual(readStoredHistory("room-normal"), [{ text: "kept", sender: "user" }]);

  appendStoredHistory("room-normal", { text: "also kept", sender: "bot" }, "normal");
  assert.deepEqual(readStoredHistory("room-normal"), [
    { text: "kept", sender: "user" },
    { text: "also kept", sender: "bot" },
  ]);
});

test("clearAllHomePagePersistedState wipes chat text, generation state, drafts and pointers", () => {
  const storage = new FakeLocalStorage();
  installFakeLocalStorage(storage);

  writeStoredHistory("room-a", [{ text: "secret", sender: "user" }]);
  writeStoredGenerationState({
    roomId: "room-a",
    roomMode: "normal",
    lastEventId: 1,
    streamedText: "streaming",
    updatedAt: Date.now(),
  });
  writeStoredActiveChatRoom("room-a", "normal");
  writeStoredHomePageViewState("chat");
  storage.setItem(STORAGE_KEYS.tasksCachePrefix + "list", "[]");
  storage.setItem(STORAGE_KEYS.setupInfoDraft, "draft text");

  clearAllHomePagePersistedState();

  assert.deepEqual(readStoredHistory("room-a"), []);
  assert.equal(readStoredGenerationState("room-a"), null);
  assert.equal(readStoredActiveChatRoom(), null);
  assert.equal(readRestorableHomePageViewState(), "setup");
  assert.equal(storage.getItem(STORAGE_KEYS.tasksCachePrefix + "list"), null);
  assert.equal(storage.getItem(STORAGE_KEYS.setupInfoDraft), null);
});

test("reconcileStoredUserScope records the first user without wiping anything", () => {
  installFakeLocalStorage(new FakeLocalStorage());

  writeStoredHistory("room-a", [{ text: "user A's message", sender: "user" }]);

  const result = reconcileStoredUserScope("42");

  assert.equal(result.changed, false);
  assert.deepEqual(readStoredHistory("room-a"), [{ text: "user A's message", sender: "user" }]);
  assert.equal(readStoredUserScope(), "user:42");
});

test("reconcileStoredUserScope keeps state when the same user returns", () => {
  installFakeLocalStorage(new FakeLocalStorage());

  reconcileStoredUserScope("42");
  writeStoredHistory("room-a", [{ text: "user A's message", sender: "user" }]);

  const result = reconcileStoredUserScope("42");

  assert.equal(result.changed, false);
  assert.deepEqual(readStoredHistory("room-a"), [{ text: "user A's message", sender: "user" }]);
});

// これがログアウトを経由しないユーザー切り替え（別アカウントでの再ログインなど）
// から、前の利用者の本文を守る最後の砦。
// This is the last line of defense protecting a previous user's text from a
// user switch that skips logout (re-login as a different account, etc.).
test("reconcileStoredUserScope wipes everything when a different user is confirmed", () => {
  installFakeLocalStorage(new FakeLocalStorage());

  reconcileStoredUserScope("42");
  writeStoredHistory("room-a", [{ text: "user A's private message", sender: "user" }]);
  writeStoredActiveChatRoom("room-a", "normal");

  const result = reconcileStoredUserScope("99");

  assert.equal(result.changed, true);
  assert.deepEqual(readStoredHistory("room-a"), []);
  assert.equal(readStoredActiveChatRoom(), null);
  assert.equal(readStoredUserScope(), "user:99");
});

test("reconcileStoredUserScope treats logout (null) as a scope of its own", () => {
  installFakeLocalStorage(new FakeLocalStorage());

  reconcileStoredUserScope("42");
  writeStoredHistory("room-a", [{ text: "user A's private message", sender: "user" }]);

  // セッション切れなどでログイン状態が失われた場合も、以後は別利用者として扱う。
  // A lost session (expiry, etc.) is treated as a different user from then on.
  const result = reconcileStoredUserScope(null);

  assert.equal(result.changed, true);
  assert.deepEqual(readStoredHistory("room-a"), []);
  assert.equal(readStoredUserScope(), "anonymous");
});
