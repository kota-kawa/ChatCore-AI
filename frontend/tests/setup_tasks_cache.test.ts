import assert from "node:assert/strict";
import test from "node:test";

import { STORAGE_KEYS } from "../scripts/core/constants";
import { readCachedTasks, writeCachedTasks } from "../scripts/setup/setup_tasks_cache";

function installLocalStorage(seed: Record<string, string> = {}) {
  const store = new Map<string, string>(Object.entries(seed));
  (globalThis as { localStorage?: unknown }).localStorage = {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => void store.set(key, value),
    removeItem: (key: string) => void store.delete(key),
  };
  return store;
}

test("task cache is scoped explicitly by authentication and locale", () => {
  installLocalStorage();
  writeCachedTasks("auth", "ja", [{ task_id: 10, name: "認証済み" }]);
  writeCachedTasks("guest", "en", [{ task_id: null, name: "Guest" }]);

  assert.equal(readCachedTasks("auth", "ja")?.[0]?.task_id, 10);
  assert.equal(readCachedTasks("guest", "en")?.[0]?.name, "Guest");
  assert.equal(readCachedTasks("auth", "en"), null);
});

test("v2 task cache entries are ignored after the identity schema change", () => {
  installLocalStorage({
    "chatcore.tasks.v2.auth:ja": JSON.stringify({
      cachedAt: Date.now(),
      tasks: [{ name: "旧形式" }],
    }),
  });

  assert.equal(STORAGE_KEYS.tasksCachePrefix, "chatcore.tasks.v3.");
  assert.equal(readCachedTasks("auth", "ja"), null);
});

test("an empty task list is cached without turning into a cache miss", () => {
  installLocalStorage();
  writeCachedTasks("auth", "ja", []);
  assert.deepEqual(readCachedTasks("auth", "ja"), []);
});
