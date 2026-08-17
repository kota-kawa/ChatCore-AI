import assert from "node:assert/strict";
import test from "node:test";

import {
  stripWebSearchArtifacts,
  stripWebSearchCitationsHtml,
  stripWebSearchSourcesHtml,
} from "../scripts/chat/memo_text";

function citationChip(url: string, label: string) {
  return [
    `<a class="web-search-citation" href="${url}" target="_blank" title="${label}">`,
    '<span class="web-search-citation__icon">',
    `<img class="web-search-citation__favicon" src="${url}/favicon.ico" alt="" referrerpolicy="no-referrer">`,
    "</span>",
    `<span class="web-search-citation__label">${label}</span>`,
    "</a>",
  ].join("");
}

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
  assert.equal(stripWebSearchCitationsHtml(text), text);
  assert.equal(stripWebSearchArtifacts(text), text);
});

test("removes an inline citation chip together with the space before it", () => {
  const text = `2026年の売上は増加しました。 ${citationChip("https://example.com/report", "Example Report")}`;

  const result = stripWebSearchCitationsHtml(text);

  assert.equal(result, "2026年の売上は増加しました。");
  assert.doesNotMatch(result, /web-search-citation/);
  assert.doesNotMatch(result, /<a\b/i);
  assert.doesNotMatch(result, /<img\b/i);
});

test("removes consecutive citation chips embedded mid sentence", () => {
  const text = [
    "前半の説明",
    citationChip("https://example.com/a", "A社"),
    " ",
    citationChip("https://example.com/b", "B社"),
    "、後半の説明。",
  ].join("");

  const result = stripWebSearchCitationsHtml(text);

  assert.equal(result, "前半の説明、後半の説明。");
});

test("keeps markdown links the answer wrote itself", () => {
  const text = "詳細は [公式ドキュメント](https://example.com/docs) を参照してください。";
  assert.equal(stripWebSearchCitationsHtml(text), text);
  assert.equal(stripWebSearchArtifacts(text), text);
});

test("removes selected-reference markers from memo text", () => {
  const text = "自然を感じられるカフェで休憩します 【personal_knowledge_result】。";

  assert.equal(stripWebSearchArtifacts(text), "自然を感じられるカフェで休憩します。");
});

test("strips both the trace block and the citation chips for a memo", () => {
  const text = [
    '<details class="web-search-sources web-search-sources--trace">',
    '<summary class="web-search-sources__summary">回答までのステップ</summary>',
    '<div class="web-search-sources__list">',
    '<ol class="web-search-sources__steps">',
    '<li class="web-search-sources__step">Web検索: テスト</li>',
    "</ol>",
    "</div>",
    "</details>",
    "",
    "# まとめ",
    "",
    `結論はこうなります。 ${citationChip("https://example.com/report", "Example Report")}`,
    "",
    "- 箇条書きも残ります。",
  ].join("\n");

  const result = stripWebSearchArtifacts(text);

  assert.doesNotMatch(result, /web-search-sources/);
  assert.doesNotMatch(result, /web-search-citation/);
  assert.doesNotMatch(result, /<details/i);
  assert.equal(result, ["# まとめ", "", "結論はこうなります。", "", "- 箇条書きも残ります。"].join("\n"));
});
