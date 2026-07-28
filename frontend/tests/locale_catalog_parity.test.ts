import assert from "node:assert/strict";
import test from "node:test";

import { enMessages } from "../lib/i18n/catalogs/en";
import { jaMessages } from "../lib/i18n/catalogs/ja";

const JAPANESE = /[぀-ヿ一-龯]/;

// 英語カタログにキーが無いと ja へフォールバックし、英語UIに日本語が出てしまう
// A key missing from the English catalog falls back to ja, leaking Japanese into the English UI
test("the English catalog covers every Japanese key", () => {
  const missing = Object.keys(jaMessages).filter((key) => !(key in enMessages));
  assert.deepEqual(missing, [], `missing English translations: ${missing.join(", ")}`);
});

test("the English catalog has no keys the Japanese catalog lacks", () => {
  const extra = Object.keys(enMessages).filter((key) => !(key in jaMessages));
  assert.deepEqual(extra, [], `unexpected English-only keys: ${extra.join(", ")}`);
});

test("no English message contains Japanese characters", () => {
  // 言語名は自称表記のままにするため除外する
  // Language names stay as endonyms, so they are excluded
  const endonymKeys = new Set(["settings.japanese", "settings.japaneseDescription", "settings.language"]);
  const leaked = Object.entries(enMessages)
    .filter(([key, value]) => !endonymKeys.has(key) && JAPANESE.test(value))
    .map(([key, value]) => `${key}: ${value}`);
  assert.deepEqual(leaked, [], `Japanese text left in the English catalog:\n${leaked.join("\n")}`);
});
