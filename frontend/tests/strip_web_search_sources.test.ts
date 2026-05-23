import assert from "node:assert/strict";
import test from "node:test";

import { stripWebSearchSourcesHtml } from "../scripts/chat/message_utils";

test("removes the simple web-search-sources details block", () => {
  const text = [
    "# 回答",
    "",
    "本文の内容です。",
    "",
    '<details class="web-search-sources">',
    '<summary class="web-search-sources__summary">参照したWebサイト</summary>',
    '<ul class="web-search-sources__list">',
    '<li class="web-search-sources__item"><a href="https://example.com">Example</a></li>',
    "</ul>",
    "</details>",
  ].join("\n");

  const result = stripWebSearchSourcesHtml(text);

  assert.doesNotMatch(result, /web-search-sources/);
  assert.doesNotMatch(result, /<details/i);
  assert.match(result, /# 回答/);
  assert.match(result, /本文の内容です。/);
});

test("removes a nested trace block prepended to the answer", () => {
  const text = [
    '<details class="web-search-sources web-search-sources--trace">',
    '<summary class="web-search-sources__summary">回答までのステップ</summary>',
    '<div class="web-search-sources__list">',
    '<ol class="web-search-sources__steps">',
    '<li class="web-search-sources__step web-search-sources__step--has-sources">',
    '<details class="web-search-sources__step-details">',
    '<summary class="web-search-sources__step-summary">Web検索: テスト</summary>',
    '<div class="web-search-sources__step-body">',
    '<ul class="web-search-sources__links"><li><a href="https://example.com">x</a></li></ul>',
    "</div>",
    "</details>",
    "</li>",
    "</ol>",
    "</div>",
    "</details>",
    "",
    "実際の回答テキスト。",
  ].join("\n");

  const result = stripWebSearchSourcesHtml(text);

  assert.doesNotMatch(result, /web-search-sources/);
  assert.doesNotMatch(result, /<details/i);
  assert.equal(result, "実際の回答テキスト。");
});

test("keeps non web-search details authored in the answer", () => {
  const text = [
    "本文。",
    "<details><summary>補足</summary><p>詳細</p></details>",
  ].join("\n");

  const result = stripWebSearchSourcesHtml(text);

  assert.equal(result, text.trim());
});

test("leaves plain text untouched", () => {
  const text = "ただのテキスト\n\n第二段落";
  assert.equal(stripWebSearchSourcesHtml(text), text);
});
