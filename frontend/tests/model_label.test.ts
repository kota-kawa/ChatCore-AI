import assert from "node:assert/strict";
import test from "node:test";

import { MODEL_OPTIONS } from "../lib/chat_page/constants";
import { formatModelOptionLabel } from "../lib/chat_page/model_label";
import { enMessages } from "../lib/i18n/catalogs/en";
import { jaMessages, type MessageKey } from "../lib/i18n/catalogs/ja";

const translate = (catalog: Record<string, string>) => (key: MessageKey) => catalog[key];

test("model labels keep the model name and localize only the usage hint", () => {
  const [groq] = MODEL_OPTIONS;
  assert.equal(
    formatModelOptionLabel(groq, translate(jaMessages), "ja"),
    "GROQ | GPT-OSS 120B（標準・高品質な応答）"
  );
  assert.equal(
    formatModelOptionLabel(groq, translate(enMessages), "en"),
    "GROQ | GPT-OSS 120B (balanced, high-quality answers)"
  );
});

// 英語表示にモデル説明の日本語が残らないことを保証する
// Guard against Japanese model descriptions leaking into the English UI
test("no model label contains Japanese characters in English", () => {
  const japanese = /[぀-ヿ一-龯（）]/;
  for (const option of MODEL_OPTIONS) {
    const label = formatModelOptionLabel(option, translate(enMessages), "en");
    assert.ok(!japanese.test(label), `English label still contains Japanese: ${label}`);
  }
});

test("every model option resolves a description in both catalogs", () => {
  for (const option of MODEL_OPTIONS) {
    assert.ok(jaMessages[option.descriptionKey], `missing ja key: ${option.descriptionKey}`);
    assert.ok(enMessages[option.descriptionKey], `missing en key: ${option.descriptionKey}`);
  }
});
