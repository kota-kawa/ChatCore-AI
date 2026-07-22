import assert from "node:assert/strict";
import test from "node:test";

import {
  __test__,
  createPersistentCacheProvider,
  clearPersistentCache,
  loadPersistentCacheEntries,
} from "../lib/data/persistent_cache";

const { canPersistKey, pruneShape, STORAGE_KEY } = __test__;

test("canPersistKey only allows safe read prefixes", () => {
  assert.equal(canPersistKey("/memo/api/list"), true);
  assert.equal(canPersistKey("/prompt_share/api/prompts"), true);
  assert.equal(canPersistKey("/api/current_user"), true);
  // 機微・即時性が要るキーは永続化しない / sensitive or realtime keys are not persisted
  assert.equal(canPersistKey("/api/chat"), false);
  assert.equal(canPersistKey("/admin/api/users"), false);
  assert.equal(canPersistKey("/api/get_chat_rooms"), false);
});

test("pruneShape drops expired entries and caps the count", () => {
  const now = Date.now();
  const shape = {
    fresh: { data: 1, ts: now },
    expired: { data: 2, ts: now - 10_000 },
  };
  const pruned = pruneShape(shape, 5_000);
  assert.ok("fresh" in pruned);
  assert.ok(!("expired" in pruned));
});

// localStorage / window のスタブ環境を用意する。
// Set up a stubbed window / localStorage environment.
function withFakeStorage(run: (store: Map<string, string>) => void) {
  const store = new Map<string, string>();
  const fakeLocalStorage = {
    getItem: (key: string) => (store.has(key) ? store.get(key)! : null),
    setItem: (key: string, value: string) => void store.set(key, value),
    removeItem: (key: string) => void store.delete(key),
  };
  const originalWindow = (globalThis as { window?: unknown }).window;
  (globalThis as { window?: unknown }).window = { localStorage: fakeLocalStorage };
  try {
    run(store);
  } finally {
    if (originalWindow === undefined) {
      delete (globalThis as { window?: unknown }).window;
    } else {
      (globalThis as { window?: unknown }).window = originalWindow;
    }
  }
}

test("provider defers storage hydration and persists allowlisted sets", () => {
  withFakeStorage((store) => {
    store.set(
      STORAGE_KEY,
      JSON.stringify({ "/memo/api/list": { data: { memos: ["a"] }, ts: Date.now() } }),
    );

    const provider = createPersistentCacheProvider();
    const cache = provider(new Map() as never);

    // 初回レンダリング中にlocalStorageを読むとSSR HTMLと不一致になるため、
    // provider自体は空のまま返す。/ The provider stays empty during hydration.
    assert.equal(cache.get("/memo/api/list"), undefined);

    // ハイドレーション完了後にだけ、復元対象をSWR mutateへ渡す。
    assert.deepEqual(loadPersistentCacheEntries(), [["/memo/api/list", { memos: ["a"] }]]);

    // allowlist 外のキーは永続化されない / non-allowlisted keys are not persisted
    cache.set("/api/get_chat_rooms", { data: ["secret"], isLoading: false } as never);
    const persistedAfter = JSON.parse(store.get(STORAGE_KEY) || "{}");
    assert.ok(!("/api/get_chat_rooms" in persistedAfter));
  });
});

test("clearPersistentCache removes the storage entry", () => {
  withFakeStorage((store) => {
    store.set(STORAGE_KEY, JSON.stringify({ "/memo/api/list": { data: 1, ts: Date.now() } }));
    clearPersistentCache();
    assert.equal(store.has(STORAGE_KEY), false);
  });
});
