import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const chatLayoutCss = readFileSync(
  new URL("../public/static/css/pages/chat/chat_layout.css", import.meta.url),
  "utf8",
);
const sharedChatCss = readFileSync(
  new URL("../public/static/css/pages/chat/shared_chat.css", import.meta.url),
  "utf8",
);

test("chat surfaces keep their rounded edge without an outer shadow", () => {
  const chatContainerRule = chatLayoutCss.match(
    /:where\(body\.chat-page, \.chat-page-shell\) #chat-container \{([^}]*)\}/,
  );
  const sharedChatShellRule = sharedChatCss.match(
    /\.shared-chat-page \.shared-chat-shell \{([^}]*)\}/,
  );

  assert.ok(chatContainerRule, "the regular chat container rule must be present");
  assert.ok(sharedChatShellRule, "the shared chat shell rule must be present");
  assert.match(chatContainerRule[1] ?? "", /border-radius:\s*var\(--radius-xl[^;]*\);/);
  assert.match(sharedChatShellRule[1] ?? "", /border-radius:\s*var\(--radius-xl[^;]*\);/);
  assert.match(chatContainerRule[1] ?? "", /box-shadow:\s*none\s*;/);
  assert.match(sharedChatShellRule[1] ?? "", /box-shadow:\s*none\s*;/);
  assert.doesNotMatch(
    chatLayoutCss,
    /#chat-container\[data-view="launching"\][^{]*\{[^}]*box-shadow:/,
    "launching state must not reintroduce an outer container shadow",
  );
});
