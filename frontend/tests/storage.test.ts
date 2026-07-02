import assert from "node:assert/strict";
import test from "node:test";

import {
  appendStoredHistory,
  clearStoredGenerationState,
  readStoredActiveChatRoom,
  readActiveStoredGenerationState,
  readStoredHomePageViewState,
  readStoredGenerationState,
  readStoredHistory,
  writeStoredActiveChatRoom,
  writeStoredHomePageViewState,
  writeStoredGenerationState,
  writeStoredHistory,
} from "../lib/chat_page/storage";
import type { StoredHistoryEntry } from "../lib/chat_page/types";
import { STORAGE_KEYS } from "../scripts/core/constants";

class FakeLocalStorage implements Storage {
  private readonly values = new Map<string, string>();
  quotaLimit: number | null = null;
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
    if (this.alwaysThrow || (this.quotaLimit !== null && value.length > this.quotaLimit)) {
      throw new DOMException("Storage quota exceeded", "QuotaExceededError");
    }
    this.values.set(key, value);
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
    roomMode: "temporary",
    lastEventId: 12,
    streamedText: "途中まで",
    updatedAt: Date.now(),
  });

  assert.equal(stored, true);
  const restored = readStoredGenerationState("room-stream");
  assert.equal(restored?.roomId, "room-stream");
  assert.equal(restored?.roomMode, "temporary");
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

test("home page view state persists setup and chat views", () => {
  const storage = new FakeLocalStorage();
  installFakeLocalStorage(storage);

  assert.equal(readStoredHomePageViewState(), "setup");

  assert.equal(writeStoredHomePageViewState("launching"), true);
  assert.equal(readStoredHomePageViewState(), "chat");

  assert.equal(writeStoredHomePageViewState("setup"), true);
  assert.equal(readStoredHomePageViewState(), "setup");
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
