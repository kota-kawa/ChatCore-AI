import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const chatMainSection = readFileSync(
  new URL("../components/chat_page/chat_main_section.tsx", import.meta.url),
  "utf8",
);
const chatInputCss = readFileSync(
  new URL("../public/static/css/pages/chat/chat_input.css", import.meta.url),
  "utf8",
);
const chatIndexCss = readFileSync(
  new URL("../public/static/css/pages/chat/index.css", import.meta.url),
  "utf8",
);

test("chat back button uses the send button's circular treatment", () => {
  assert.match(
    chatMainSection,
    /id="back-to-setup"[\s\S]*?className="chat-back-btn cc-press"/,
    "the header back control must use its dedicated visual class",
  );
  assert.match(
    chatInputCss,
    /#send-btn,[\s\S]*?\.chat-back-btn\s*\{[\s\S]*?border-radius:\s*50%\s*;/,
    "the back control must share the circular button layout with send",
  );
  assert.match(
    chatInputCss,
    /#send-btn::before,[\s\S]*?\.chat-back-btn::before\s*\{[\s\S]*?linear-gradient\(/,
    "the back control must share the send button's green gradient surface",
  );
  assert.match(
    chatIndexCss,
    /#send-btn,[\s\S]*?\.setup-send-btn,[\s\S]*?\.chat-back-btn,/,
    "the back control must receive the chat page's primary button tokens",
  );
});

test("mobile chat back button keeps the send button's compact size", () => {
  const mobileChatInputCss = chatInputCss.slice(chatInputCss.indexOf("@media (max-width: 576px)"));

  assert.match(
    mobileChatInputCss,
    /#send-btn,[\s\S]*?\.chat-back-btn\s*\{[\s\S]*?flex-basis:\s*48px[\s\S]*?width:\s*48px[\s\S]*?height:\s*48px\s*;/,
    "the mobile back control must match the send button's 48px size",
  );
});
