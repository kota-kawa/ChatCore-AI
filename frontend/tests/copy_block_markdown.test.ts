import assert from "node:assert/strict";
import test from "node:test";

import { formatLLMOutput, formatMemoOutput } from "../scripts/chat/chat_ui";
import { parseCopyBlockInfo, stripCopyBlockFences } from "../scripts/chat/copy_block_markdown";

const EMAIL_BODY = ["開発チーム各位", "", "お疲れさまです。4月25日に説明会を実施します。"].join("\n");

function copyFence(info: string, body: string) {
  return ["```" + info, body, "```"].join("\n");
}

test("parseCopyBlockInfo splits the fence name from its label", () => {
  assert.deepEqual(parseCopyBlockInfo("chatcore-copy メール本文"), {
    isCopyBlock: true,
    label: "メール本文",
  });
  assert.deepEqual(parseCopyBlockInfo("chatcore-copy"), { isCopyBlock: true, label: "" });
});

// モデルはフェンス名の区切りを揺らすので、判定側だけ緩めに受ける。
test("parseCopyBlockInfo accepts the spellings models drift into", () => {
  assert.equal(parseCopyBlockInfo("chatcore copy").isCopyBlock, true);
  assert.equal(parseCopyBlockInfo("chatcore_copy Reply").isCopyBlock, true);
  assert.equal(parseCopyBlockInfo("CHATCORE-COPY").isCopyBlock, true);
});

test("parseCopyBlockInfo leaves ordinary code fences alone", () => {
  assert.equal(parseCopyBlockInfo("python").isCopyBlock, false);
  assert.equal(parseCopyBlockInfo("text").isCopyBlock, false);
  assert.equal(parseCopyBlockInfo("").isCopyBlock, false);
  assert.equal(parseCopyBlockInfo("copy").isCopyBlock, false);
});

test("formatLLMOutput renders a copy fence as a copy card with a copy button", () => {
  const html = formatLLMOutput(copyFence("chatcore-copy メール本文", EMAIL_BODY));

  assert.match(html, /<div class="copy-block-container">/);
  assert.match(html, /<span class="copy-block-label">メール本文<\/span>/);
  assert.match(html, /<button class="copy-block-copy-btn" type="button" title="Copy">/);
  assert.match(html, /<pre class="copy-block-text">開発チーム各位/);
  // コードブロック扱いにならないこと（等幅・ハイライトを付けない）。
  assert.doesNotMatch(html, /code-block-container/);
  assert.doesNotMatch(html, /hljs/);
  // 内部マーカーが画面に出ないこと。
  assert.doesNotMatch(html, /chatcore-copy/);
});

test("formatLLMOutput escapes markup inside a copy card", () => {
  const html = formatLLMOutput(copyFence("chatcore-copy", '<img src=x onerror="alert(1)">'));

  assert.match(html, /&lt;img src=x onerror=/);
  assert.doesNotMatch(html, /<img/);
});

// 枠の中はプレーンテキストのまま。画面の文字列とコピーされる文字列を一致させるため、
// Markdown 記法は解釈せずそのまま見せる。
test("formatLLMOutput keeps copy card content as plain text", () => {
  const html = formatLLMOutput(copyFence("chatcore-copy", "**太字ではない** - 箇条書きでもない"));

  assert.match(html, /\*\*太字ではない\*\* - 箇条書きでもない/);
  assert.doesNotMatch(html, /<strong>/);
  assert.doesNotMatch(html, /<li>/);
});

// 生成中は閉じフェンスがまだ来ない。この間も枠として描き、散文の整形（key:value の
// 箇条書き化）に掛からないこと。掛かると閉じた瞬間に画面が組み替わる。
test("formatLLMOutput renders an unterminated copy fence as a card without reflowing the body", () => {
  const html = formatLLMOutput(["本文です。", "", "```chatcore-copy メール本文", "件名: 説明会のご案内", "日時: 4月25日"].join("\n"));

  assert.match(html, /<div class="copy-block-container">/);
  assert.match(html, /件名: 説明会のご案内\n日時: 4月25日/);
  assert.doesNotMatch(html, /<li>/);
});

test("formatLLMOutput still renders ordinary code fences as code blocks", () => {
  const html = formatLLMOutput(["```python", "print(1)", "```"].join("\n"));

  assert.match(html, /code-block-container/);
  assert.match(html, /code-block-copy-btn/);
  assert.doesNotMatch(html, /copy-block-container/);
});

// メモ側にはコピーボタンの委譲ハンドラが無いため、押せないボタンは描かない。
test("formatMemoOutput renders a copy card without a copy button", () => {
  const html = formatMemoOutput(copyFence("chatcore-copy メール本文", EMAIL_BODY));

  assert.match(html, /<div class="copy-block-container">/);
  assert.match(html, /<span class="copy-block-label">メール本文<\/span>/);
  assert.doesNotMatch(html, /copy-block-copy-btn/);
  assert.doesNotMatch(html, /memo-code-block-lang/);
});

test("stripCopyBlockFences removes the delimiters and keeps the wording", () => {
  const text = ["以下が本文です。", "", copyFence("chatcore-copy メール本文", EMAIL_BODY), "", "調整点があれば教えてください。"].join("\n");

  assert.equal(
    stripCopyBlockFences(text),
    ["以下が本文です。", "", EMAIL_BODY, "", "調整点があれば教えてください。"].join("\n"),
  );
});

test("stripCopyBlockFences leaves other fenced blocks intact", () => {
  const text = ["```python", "print(1)", "```", "", copyFence("chatcore-copy", "返信文")].join("\n");

  assert.equal(stripCopyBlockFences(text), ["```python", "print(1)", "```", "", "返信文"].join("\n"));
});

test("stripCopyBlockFences returns text without a copy fence unchanged", () => {
  const text = ["説明です。", "```text", "alpha", "```"].join("\n");

  assert.equal(stripCopyBlockFences(text), text);
});

// 生成が途中で止まった応答でも、開いたままのフェンス行を残さない。
test("stripCopyBlockFences drops an unterminated opening fence", () => {
  assert.equal(stripCopyBlockFences(["```chatcore-copy 返信案", "ご連絡ありがとうございます。"].join("\n")), "ご連絡ありがとうございます。");
});
