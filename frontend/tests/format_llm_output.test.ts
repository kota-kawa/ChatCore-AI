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

test("formatLLMOutput turns loose bracketed LaTeX into readable math blocks", () => {
  const response = [
    "結論",
    "- Homework 1:",
    "",
    "(p_0) は正規化定数で、",
    "[",
    "p_0=\\left[\\sum_{k=0}^{m-1}\\frac{(\\lambda/\\mu)^k}{k!}+\\frac{(\\lambda/\\mu)^m}{m!,(1-\\rho)}\\right]^{-1},",
    "\\qquad \\rho=\\frac{\\lambda}{m\\mu}",
    "]",
    "(p_k) は",
    "[",
    "p_k=",
    "\\begin{cases}",
    "\\dfrac{(\\lambda/\\mu)^k}{k!},p_0 & (0\\le k\\le m)\\[6pt]",
    "\\dfrac{(\\lambda/\\mu)^m}{m!},\\rho^{,k-m},p_0 & (k>m)",
    "\\end{cases}",
    "]",
  ].join("\n");

  const html = formatLLMOutput(response);

  assert.match(html, /<h2>結論<\/h2>/);
  assert.match(html, /<span class="math-inline">p_0<\/span>/);
  assert.match(html, /<div class="math-display">/);
  assert.match(html, /∑_\{k=0\}\^\{m-1\}/);
  assert.match(html, /λ\/μ/);
  assert.match(html, /ρ=/);
  assert.doesNotMatch(html, /\\left/);
  assert.doesNotMatch(html, /\\begin\{cases\}/);
  assert.doesNotMatch(html, /\\\[6pt\]/);
});
