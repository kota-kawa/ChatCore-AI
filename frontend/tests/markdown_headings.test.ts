import assert from "node:assert/strict";
import test from "node:test";

import { demoteMarkdownHeadings } from "../scripts/core/markdown_headings";

test("demoteMarkdownHeadings shifts every heading level and keeps the closing tags in sync", () => {
  const html = "<h1>タイトル</h1><h2>節</h2><p>本文</p>";

  assert.equal(
    demoteMarkdownHeadings(html, 2),
    "<h3>タイトル</h3><h4>節</h4><p>本文</p>"
  );
});

test("demoteMarkdownHeadings caps the shifted level at h6 and preserves attributes", () => {
  const html = '<h5 class="md-heading">深い見出し</h5><h6>最深</h6>';

  assert.equal(
    demoteMarkdownHeadings(html, 2),
    '<h6 class="md-heading">深い見出し</h6><h6>最深</h6>'
  );
});

test("demoteMarkdownHeadings leaves the HTML untouched without a positive offset", () => {
  const html = "<h1>タイトル</h1>";

  assert.equal(demoteMarkdownHeadings(html, 0), html);
  assert.equal(demoteMarkdownHeadings(html, -1), html);
  assert.equal(demoteMarkdownHeadings("", 2), "");
});

test("demoteMarkdownHeadings does not touch escaped headings inside code blocks", () => {
  // サニタイズ済みHTMLではコードブロック内の見出しはエスケープされているため対象外になる
  // Headings inside code blocks are escaped in sanitized HTML, so they stay as-is
  const html = "<pre><code>&lt;h1&gt;サンプル&lt;/h1&gt;\n# 見出し</code></pre>";

  assert.equal(demoteMarkdownHeadings(html, 2), html);
});
