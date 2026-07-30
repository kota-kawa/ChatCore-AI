import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const chatLayoutCss = readFileSync(
  new URL("../public/static/css/pages/chat/chat_layout.css", import.meta.url),
  "utf8",
);
const chatMessagesCss = readFileSync(
  new URL("../public/static/css/pages/chat/chat_messages.css", import.meta.url),
  "utf8",
);

test("mobile chat header uses a transparent surface with readable controls", () => {
  assert.match(
    chatLayoutCss,
    /@media \(max-width: 576px\)[\s\S]*?\.chat-header\s*\{[\s\S]*?background:\s*transparent\s*;[\s\S]*?box-shadow:\s*none\s*;/,
    "the mobile header must not restore the green background or divider shadow",
  );
  assert.match(
    chatLayoutCss,
    /\.chat-header \.icon-button\s*\{[\s\S]*?backdrop-filter:\s*blur\(14px\) saturate\(135%\)\s*;/,
    "header actions must remain readable over the transparent surface",
  );
});

test("mobile chat messages fade as they approach the transparent header", () => {
  assert.match(
    chatMessagesCss,
    /@media \(max-width: 576px\)[\s\S]*?\.chat-messages\s*\{[\s\S]*?-webkit-mask-image:\s*linear-gradient\([\s\S]*?transparent 0[\s\S]*?#000 4\.25rem/,
    "the mobile message scroller must include the WebKit-compatible top fade",
  );
  assert.match(
    chatMessagesCss,
    /\n\s+mask-image:\s*linear-gradient\([\s\S]*?transparent 0[\s\S]*?#000 4\.25rem/,
    "the mobile message scroller must include the standard top fade",
  );
});
