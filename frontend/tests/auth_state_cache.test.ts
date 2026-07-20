import assert from "node:assert/strict";
import test from "node:test";

import {
  AUTH_BOOT_ATTRIBUTE,
  isCachedAuthStateFresh,
  readCachedAuthState,
  writeCachedAuthState,
} from "../scripts/core/auth_state_cache";
import { CACHE_TTL_MS, STORAGE_KEYS } from "../scripts/core/constants";

function installLocalStorage(seed: Record<string, string> = {}) {
  const store = new Map<string, string>(Object.entries(seed));
  (globalThis as { localStorage?: unknown }).localStorage = {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => void store.set(key, value),
  };
  return store;
}

test("readCachedAuthState maps the stored flag to a boolean", () => {
  installLocalStorage({ [STORAGE_KEYS.authStateCache]: "1" });
  assert.equal(readCachedAuthState(), true);

  installLocalStorage({ [STORAGE_KEYS.authStateCache]: "0" });
  assert.equal(readCachedAuthState(), false);
});

test("readCachedAuthState returns null when nothing usable is stored", () => {
  installLocalStorage();
  assert.equal(readCachedAuthState(), null);

  installLocalStorage({ [STORAGE_KEYS.authStateCache]: "true" });
  assert.equal(readCachedAuthState(), null);
});

test("writeCachedAuthState records the value alongside a timestamp", () => {
  const store = installLocalStorage();
  writeCachedAuthState(true);

  assert.equal(store.get(STORAGE_KEYS.authStateCache), "1");
  // タイムスタンプが無いと isCachedAuthStateFresh が常に false になる
  // Without the timestamp isCachedAuthStateFresh would always report false
  assert.ok(Number.isFinite(Number(store.get(STORAGE_KEYS.authStateCachedAt))));
  assert.equal(isCachedAuthStateFresh(), true);
});

test("isCachedAuthStateFresh expires entries past the TTL", () => {
  installLocalStorage({
    [STORAGE_KEYS.authStateCache]: "1",
    [STORAGE_KEYS.authStateCachedAt]: String(Date.now() - CACHE_TTL_MS.authState - 1),
  });
  assert.equal(isCachedAuthStateFresh(), false);

  installLocalStorage({ [STORAGE_KEYS.authStateCache]: "1" });
  assert.equal(isCachedAuthStateFresh(), false);
});

test("the boot attribute matches the one the bootstrap script sets", () => {
  assert.equal(AUTH_BOOT_ATTRIBUTE, "data-cc-auth");
});

test("readCachedAuthState survives a throwing localStorage", () => {
  (globalThis as { localStorage?: unknown }).localStorage = {
    getItem: () => {
      throw new Error("localStorage disabled");
    },
    setItem: () => {
      throw new Error("localStorage disabled");
    },
  };

  assert.equal(readCachedAuthState(), null);
  assert.equal(isCachedAuthStateFresh(), false);
  assert.doesNotThrow(() => writeCachedAuthState(true));
});
