import assert from "node:assert/strict";
import test from "node:test";

import {
  getStoredThemePreference,
  setThemePreference,
  shouldSendThemePreference,
} from "../scripts/core/theme";

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

test("theme preference is sent only for explicit theme reads", () => {
  assert.equal(shouldSendThemePreference("What theme am I using?"), true);
  assert.equal(shouldSendThemePreference("What's my theme?"), true);
  assert.equal(shouldSendThemePreference("What is my current theme setting?"), true);
  assert.equal(shouldSendThemePreference("今のテーマ設定を教えて"), true);
  assert.equal(shouldSendThemePreference("What is the theme of this poem?"), false);
  assert.equal(shouldSendThemePreference("What is the current theme of this poem?"), false);
  assert.equal(shouldSendThemePreference("What is my theme in this poem?"), false);
  assert.equal(shouldSendThemePreference("この詩のテーマを教えて"), false);
  assert.equal(shouldSendThemePreference("Change my theme to dark"), false);
  assert.equal(shouldSendThemePreference("テーマをダークにして"), false);
  assert.equal(shouldSendThemePreference("Summarize my travel memo"), false);
  assert.equal(shouldSendThemePreference("What's my color scheme for the brand?"), false);
  assert.equal(shouldSendThemePreference("What is my theme song for this trip?"), false);
  assert.equal(shouldSendThemePreference("What is my theme right now?"), true);
});
