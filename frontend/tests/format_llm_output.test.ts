import assert from "node:assert/strict";
import test from "node:test";

import { formatLLMOutput } from "../scripts/chat/chat_ui";

// 回答直後（=セッション内で最初の formatLLMOutput 呼び出し）でも、Web 検索の
// 「回答までのステップ」ブロックがエスケープされず HTML として描画されること。
// 以前は markedParser の遅延初期化が原因で初回だけフォールバック描画になり、
// 生成直後はステップが表示されず、再読込で初めて表示される不具合があった。
test("first formatLLMOutput call renders the web-search trace block instead of escaping it", () => {
  const trace = [
    '<details class="web-search-sources web-search-sources--trace">',
    '<summary class="web-search-sources__summary">',
    '<span class="web-search-sources__label">回答までのステップ</span>',
    "</summary>",
    '<div class="web-search-sources__list">',
    '<ol class="web-search-sources__steps">',
    '<li class="web-search-sources__step">',
    '<span class="web-search-sources__index">1</span>',
    '<span class="web-search-sources__content">',
    '<span class="web-search-sources__title">検索が必要か判断</span>',
    "</span>",
    "</li>",
    "</ol>",
    "</div>",
    "</details>",
  ].join("\n");
  const html = formatLLMOutput(`${trace}\n\n回答本文です。`);

  assert.match(html, /<details class="web-search-sources web-search-sources--trace">/);
  assert.match(html, /回答までのステップ/);
  assert.doesNotMatch(html, /&lt;details/);
});
