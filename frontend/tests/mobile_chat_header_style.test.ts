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
const mobileChatLayoutCss = chatLayoutCss.slice(chatLayoutCss.indexOf("@media (max-width: 576px)"));

test("mobile chat header and controls stay fully transparent", () => {
  assert.match(
    mobileChatLayoutCss,
    /\.chat-header\s*\{[\s\S]*?background:\s*transparent\s*;[\s\S]*?box-shadow:\s*none\s*;/,
    "the mobile header must not restore the green background or divider shadow",
  );
  assert.match(
    mobileChatLayoutCss,
    /\.chat-header \.icon-button\s*\{[\s\S]*?background:\s*transparent\s*;[\s\S]*?border:\s*1px solid transparent\s*;[\s\S]*?box-shadow:\s*none\s*;[\s\S]*?backdrop-filter:\s*none\s*;/,
    "header actions must not add visible cards to the transparent surface",
  );
  assert.match(
    mobileChatLayoutCss,
    /\.chat-header-model-trigger\s*\{[\s\S]*?background:\s*transparent\s*;[\s\S]*?border-color:\s*transparent\s*;[\s\S]*?box-shadow:\s*none\s*;/,
    "the model selector must stay visually transparent with the header",
  );
  assert.match(
    mobileChatLayoutCss,
    /\.chat-header :is\(\.icon-button, \.chat-header-model-trigger\):is\(:hover, :focus, :focus-visible, :active\)\s*\{[\s\S]*?background:\s*transparent\s*;[\s\S]*?box-shadow:\s*none\s*;[\s\S]*?filter:\s*none\s*;/,
    "interactive header controls must not add a visible surface or shadow",
  );
});

test("mobile chat messages fade as they approach the transparent header", () => {
  const mobileChatMessagesCss = chatMessagesCss.slice(chatMessagesCss.indexOf("@media (max-width: 576px)"));
  assert.match(
    mobileChatMessagesCss,
    /-webkit-mask-image:\s*linear-gradient\([\s\S]*?transparent 0[\s\S]*?#000 var\(--chat-fade-top\)/,
    "the mobile message scroller must include the WebKit-compatible top fade",
  );
  assert.match(
    mobileChatMessagesCss,
    /\n\s+mask-image:\s*linear-gradient\([\s\S]*?transparent 0[\s\S]*?#000 var\(--chat-fade-top\)/,
    "the mobile message scroller must include the standard top fade",
  );
});
