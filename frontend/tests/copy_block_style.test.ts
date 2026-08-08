import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const copyBlockCss = readFileSync(
  new URL("../public/static/css/components/copy_block.css", import.meta.url),
  "utf8",
);
const appEntry = readFileSync(new URL("../pages/_app.tsx", import.meta.url), "utf8");

function ruleBody(css: string, selector: string) {
  const start = css.indexOf(selector + " {");
  assert.notEqual(start, -1, `${selector} must be declared`);
  const body = css.slice(start + selector.length);
  return body.slice(0, body.indexOf("}"));
}

// 枠の中身は「見えている文字列＝コピーされる文字列」であることが前提なので、
// 改行を潰したり本文を横スクロールへ逃がしたりしてはいけない。
// The card promises that what is shown is what gets copied, so newlines must be
// kept and the body must wrap instead of escaping into a horizontal scroller.
test("the copy card body keeps newlines and wraps long lines", () => {
  const body = ruleBody(copyBlockCss, ".copy-block-container .copy-block-text");

  assert.match(body, /white-space:\s*pre-wrap\s*;/);
  assert.match(body, /word-break:\s*break-word\s*;/);
  assert.doesNotMatch(body, /overflow-x:\s*auto\s*;/);
});

// chat_messages.css の `.bot-message pre` が等幅フォントと独自の padding を当てるため、
// コンテナ込みのセレクタで詳細度を上げていないと枠の中だけコードのように見える。
// `.bot-message pre` in chat_messages.css imposes monospace and its own padding, so
// the rule has to be scoped through the container to outrank it.
test("the copy card body outranks the bot message pre rule and uses the body font", () => {
  assert.match(copyBlockCss, /\.copy-block-container \.copy-block-text \{/);
  assert.match(ruleBody(copyBlockCss, ".copy-block-container .copy-block-text"), /font-family:\s*inherit\s*;/);
});

test("the copy button sits at the top right of the card header", () => {
  const header = ruleBody(copyBlockCss, ".copy-block-header");

  assert.match(header, /display:\s*flex\s*;/);
  assert.match(header, /justify-content:\s*space-between\s*;/);
  // ラベルが無いフェンスでもヘッダーが潰れず、ボタンが右上に残ること。
  // A fence with no label must still leave the header its height, keeping the button in place.
  assert.match(header, /min-height:\s*[\d.]+rem\s*;/);
});

// 成功と失敗をアイコンの形だけで伝えると色覚差のある読者に届かないため、色も変える。
// Shape alone would not reach every reader, so the outcome changes colour too.
test("copy feedback is carried by colour as well as the icon swap", () => {
  assert.match(copyBlockCss, /\.copy-block-copy-btn \.bi-check-lg \{[\s\S]*?color:/);
  assert.match(copyBlockCss, /\.copy-block-copy-btn \.bi-x-lg \{[\s\S]*?color:/);
});

// 色は base/variables.css のトークン経由にしておく。トークンは [data-theme="dark"] で
// 差し替わるので、ダークテーマ用の重複ルールを書かずに追随できる。
// Colours go through the tokens in base/variables.css, which are redefined under
// [data-theme="dark"], so the card follows the dark theme without duplicated rules.
test("the card takes its colours from the theme tokens", () => {
  const container = ruleBody(copyBlockCss, ".copy-block-container");

  assert.match(container, /background:\s*var\(--surface-secondary/);
  assert.match(container, /border:\s*1px solid var\(--border-default/);
  assert.match(ruleBody(copyBlockCss, ".copy-block-container .copy-block-text"), /color:\s*var\(--text-dark/);
});

test("the copy card stylesheet is loaded by the app entry point", () => {
  assert.match(appEntry, /import "\.\.\/public\/static\/css\/components\/copy_block\.css";/);
});
