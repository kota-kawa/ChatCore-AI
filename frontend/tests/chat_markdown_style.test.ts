import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const markdownCss = readFileSync(
  new URL("../public/static/css/pages/chat/chat_markdown.css", import.meta.url),
  "utf8",
);
const chatMessagesCss = readFileSync(
  new URL("../public/static/css/pages/chat/chat_messages.css", import.meta.url),
  "utf8",
);
const appEntry = readFileSync(new URL("../pages/_app.tsx", import.meta.url), "utf8");

function ruleBody(css: string, selector: string) {
  const start = css.indexOf(selector + " {");
  assert.notEqual(start, -1, `${selector} must be declared`);
  const body = css.slice(start + selector.length);
  return body.slice(0, body.indexOf("}"));
}

// 本文の組版は chat_markdown.css に集約する。器（吹き出し・出典UI）を持つ
// chat_messages.css へ書き戻すと、また 3000 行のファイルへ戻ってしまう。
// The prose rules live in chat_markdown.css; folding them back into
// chat_messages.css, which owns the message shell, rebuilds the 3000-line file.
test("the answer body stylesheet is loaded after the message shell stylesheet", () => {
  const shellIndex = appEntry.indexOf('import "../public/static/css/pages/chat/chat_messages.css";');
  const proseIndex = appEntry.indexOf('import "../public/static/css/pages/chat/chat_markdown.css";');

  assert.notEqual(shellIndex, -1, "chat_messages.css must be imported");
  assert.notEqual(proseIndex, -1, "chat_markdown.css must be imported");
  assert.ok(proseIndex > shellIndex, "the prose rules must be able to override the shell rules");
});

// インラインコードが Bootstrap 既定のピンクだった頃、緑のサービスの中で
// そこだけ別サイトのように見えていた。色はブランドトークンから作る。
// Inline code used to keep Bootstrap's pink, which read as a different site inside
// the green product. Its colours are mixed from the brand token instead.
test("inline code takes its colour from the brand token, never the bootstrap pink", () => {
  const body = ruleBody(
    markdownCss,
    ':where(body.chat-page, .chat-page-shell) .bot-message code:not([class])',
  );

  assert.match(body, /color:\s*var\(--md-code-ink\)/);
  assert.doesNotMatch(markdownCss, /#d63384/i);
  assert.doesNotMatch(markdownCss, /#f472b6/i);
  assert.doesNotMatch(chatMessagesCss, /#d63384/i);
  assert.doesNotMatch(chatMessagesCss, /#f472b6/i);
});

// ダークテーマの `code` ルールが `pre code` まで塗ってしまい、コードブロックの
// 全行に半透明の帯とピンクの文字が乗っていた。素の code だけを対象にする。
// The dark-theme `code` rule also repainted `pre code`, leaving every line of a code
// block with a translucent band and pink text. Only bare inline code is targeted now.
test("code inside a block is never repainted by the inline code rule", () => {
  const inlineSelectors = markdownCss.match(/^[^\n]*\.bot-message code[^\n]*$/gm) ?? [];

  assert.ok(inlineSelectors.length > 0, "an inline code rule must exist");
  inlineSelectors.forEach((selector) => {
    assert.match(
      selector,
      /code:not\(\[class\]\)/,
      `${selector.trim()} would also match the highlighted <code class="hljs …"> inside a code block`,
    );
  });
});

// 出典UIやコピー枠はアプリが組み立てた HTML で、class を持つ。本文用の
// リスト・リンク装飾がそこへ漏れると、手順の行に中黒が生えたりする。
// The source UI and copy cards are app-built HTML carrying classes. Prose list and
// link decoration leaking into them would sprout bullets on the trace steps.
test("prose list and link styling is scoped away from the app-built blocks", () => {
  const leaking = (markdownCss.match(/^[^\n]*\.bot-message (?:ul|ol|a)(?![\w-])[^\n]*$/gm) ?? []).filter(
    (selector) => !selector.includes(":not([class])"),
  );

  assert.deepEqual(leaking, [], "list and link rules must be scoped with :not([class])");
});

// 引用は日本語では斜体にしない。和文に本物のイタリックは無く、合成された
// 斜体はブラウザ任せの粗い変形になって読みにくい。
// Quotes are never italic: Japanese has no true italic, and the synthesized slant is a
// coarse browser transform that hurts legibility.
test("blockquotes are not rendered in synthesized italic", () => {
  const body = ruleBody(markdownCss, ':where(body.chat-page, .chat-page-shell) .bot-message blockquote');

  assert.match(body, /font-style:\s*normal\s*;/);
});
