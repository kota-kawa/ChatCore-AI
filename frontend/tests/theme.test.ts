import assert from "node:assert/strict";
import test from "node:test";

import { getStoredThemePreference, setThemePreference } from "../scripts/core/theme";

class FakeLocalStorage {
  private readonly values = new Map<string, string>();

  getItem(key: string) {
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string) {
    this.values.set(key, value);
  }
}

function installThemeWindow(storage: FakeLocalStorage) {
  Object.defineProperty(globalThis, "window", {
    value: { localStorage: storage },
    configurable: true,
  });
}

test("theme defaults to light when no preference has been saved", () => {
  installThemeWindow(new FakeLocalStorage());

  assert.equal(getStoredThemePreference(), "light");
});

test("system theme preference remains explicit and persists across reloads", () => {
  const storage = new FakeLocalStorage();
  installThemeWindow(storage);

  setThemePreference("auto");

  assert.equal(storage.getItem("chatcore-theme"), "auto");
  assert.equal(getStoredThemePreference(), "auto");
});
