import assert from "node:assert/strict";
import test from "node:test";

import { renderMarkdownToSafeHtmlOnServer } from "../lib/server/markdown_ssr";

// サーバーサイドMarkdownレンダラーのテスト（SSRで本文HTMLを出力するSEO対策の回帰防止）
// Tests for the server-side Markdown renderer (regression guard for the SEO fix that outputs the body HTML during SSR)

test("renderMarkdownToSafeHtmlOnServer converts markdown to HTML on the server", () => {
  const html = renderMarkdownToSafeHtmlOnServer("# 見出し\n\n本文テキスト");
  assert.match(html, /<h1>見出し<\/h1>/);
  assert.match(html, /本文テキスト/);
});

test("renderMarkdownToSafeHtmlOnServer strips dangerous markup", () => {
  const html = renderMarkdownToSafeHtmlOnServer('<script>alert(1)</script><img src="x" onerror="alert(1)">安全な本文');
  assert.doesNotMatch(html, /<script/i);
  assert.doesNotMatch(html, /onerror/i);
  assert.match(html, /安全な本文/);
});

test("renderMarkdownToSafeHtmlOnServer blocks javascript: URLs and hardens links", () => {
  const html = renderMarkdownToSafeHtmlOnServer("[リンク](https://example.com) [悪性](javascript:alert(1))");
  assert.match(html, /href="https:\/\/example\.com"/);
  assert.match(html, /target="_blank"/);
  assert.match(html, /rel="noopener noreferrer"/);
  assert.doesNotMatch(html, /javascript:/i);
});

test("renderMarkdownToSafeHtmlOnServer returns an empty string for empty input", () => {
  assert.equal(renderMarkdownToSafeHtmlOnServer(""), "");
  assert.equal(renderMarkdownToSafeHtmlOnServer(null), "");
  assert.equal(renderMarkdownToSafeHtmlOnServer(undefined), "");
});

test("renderMarkdownToSafeHtmlOnServer renders fenced python code blocks", () => {
  const html = renderMarkdownToSafeHtmlOnServer("```python\nprint('hello')\n```");
  assert.match(html, /<pre><code class="language-python">/);
  assert.match(html, /print\(&#39;hello&#39;\)|print\('hello'\)/);
});
