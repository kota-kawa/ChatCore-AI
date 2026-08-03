import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { WORD_REVEAL_DURATION_MS } from "../lib/chat_page/streaming_word_reveal";

const streamingTextCss = readFileSync(
  new URL("../public/static/css/components/streaming_text.css", import.meta.url),
  "utf8",
);
const chatMessagesCss = readFileSync(
  new URL("../public/static/css/pages/chat/chat_messages.css", import.meta.url),
  "utf8",
);
const appEntry = readFileSync(new URL("../pages/_app.tsx", import.meta.url), "utf8");

test("streamed words fade in from a blur", () => {
  assert.match(
    streamingTextCss,
    /\.streaming-word\s*\{[\s\S]*?animation:\s*streamingWordReveal var\(--streaming-word-duration, \d+ms\)[\s\S]*?both\s*;/,
    "each streamed word must run the reveal animation driven by the shared duration",
  );
  assert.match(
    streamingTextCss,
    /@keyframes streamingWordReveal\s*\{[\s\S]*?from\s*\{[\s\S]*?opacity:\s*0\s*;[\s\S]*?filter:\s*blur\([^)]+\)\s*;[\s\S]*?to\s*\{[\s\S]*?opacity:\s*1\s*;[\s\S]*?filter:\s*blur\(0\)\s*;/,
    "the reveal must animate opacity together with the blur so words materialize",
  );
  assert.match(
    streamingTextCss,
    /\d+%\s*\{[\s\S]*?opacity:\s*0\.\d+\s*;/,
    "an early keyframe must hold the word near-transparent so the fade stays visible at speed",
  );
});

test("the CSS fallback duration matches the JavaScript reveal duration", () => {
  const fallback = streamingTextCss.match(/--streaming-word-duration,\s*(\d+)ms/);
  assert.ok(fallback, "the animation must declare a fallback duration");
  assert.equal(Number(fallback[1]), WORD_REVEAL_DURATION_MS);
});

test("reduced motion turns the streamed word animation off", () => {
  const reducedMotion = streamingTextCss.slice(
    streamingTextCss.indexOf("@media (prefers-reduced-motion: reduce)"),
  );
  assert.match(
    reducedMotion,
    /\.streaming-word\s*\{[\s\S]*?animation:\s*none\s*;[\s\S]*?opacity:\s*1\s*;[\s\S]*?filter:\s*none\s*;/,
    "words must stay fully visible when the reader asked for reduced motion",
  );
});

test("the streaming text stylesheet is loaded by the app entry point", () => {
  assert.match(appEntry, /import "\.\.\/public\/static\/css\/components\/streaming_text\.css";/);
});

test("bot messages never re-break earlier lines while text streams in", () => {
  // pretty/balance は段落の後ろ数行をまとめて組み直すため、追記のたびに
  // すでに表示済みの文字の折り返しが変わり、狭い画面で文字がズレて見える。
  // pretty/balance re-break the last lines of a paragraph as a group, so an
  // append can move text the reader is already on. Narrow screens show it worst.
  // 同じセレクタの宣言ブロックは複数あるため、すべてまとめて確認する。
  // The selector has more than one rule block, so check every one of them.
  const declarations = chatMessagesCss
    .split(":where(body.chat-page, .chat-page-shell) .bot-message {")
    .slice(1)
    // コメント内の説明文を宣言と誤検出しないよう先に取り除く。
    // Strip comments first so the explanation is not read as a declaration.
    .map((block) => {
      const withoutComments = block.replace(/\/\*[\s\S]*?\*\//g, "");
      return withoutComments.slice(0, withoutComments.indexOf("}"));
    });
  assert.ok(declarations.length > 0, "the bot message rule must exist");

  declarations.forEach((block) => {
    assert.doesNotMatch(
      block,
      /text-wrap:\s*(pretty|balance)/,
      "streamed bot text must use greedy wrapping so appended characters never move placed text",
    );
  });
  assert.ok(
    declarations.some((block) => /text-wrap:\s*wrap\s*;/.test(block)),
    "greedy wrapping must be declared explicitly so pretty is not reintroduced by inheritance",
  );
});

test("no trailing cursor dot runs ahead of the fading words", () => {
  // 透明のまま開始待ちの語がある間、ドットだけが先行して見えてしまうため廃止。
  // Removed: with queued transparent words a dot would run ahead of the text.
  assert.doesNotMatch(chatMessagesCss, /streamCursorBreathe/);
  assert.doesNotMatch(
    chatMessagesCss,
    /\.bot-message--streaming[^{]*::after\s*\{[\s\S]*?border-radius:\s*50%/,
    "the breathing dot after the streamed text must stay removed",
  );
});
