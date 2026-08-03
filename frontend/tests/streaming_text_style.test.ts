import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { WORD_REVEAL_DURATION_MS } from "../lib/chat_page/streaming_word_reveal";

const streamingTextCss = readFileSync(
  new URL("../public/static/css/components/streaming_text.css", import.meta.url),
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
