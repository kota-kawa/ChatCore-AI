import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const chatMessagesCss = readFileSync(
  new URL("../public/static/css/pages/chat/chat_messages.css", import.meta.url),
  "utf8",
);

test("opening the task prompt never widens the fit-content bubble", () => {
  assert.match(
    chatMessagesCss,
    /\.task-prompt-disclosure__body\s*\{[^}]*?contain:\s*inline-size\s*;/,
    "the disclosed prompt must stay out of the bubble's width calculation",
  );
});

test("a task-launch bubble keeps a readable width whether open or closed", () => {
  const floor = chatMessagesCss.match(
    /\.user-message-wrapper:has\(\.task-prompt-disclosure\)\s*\{[^}]*?min-inline-size:\s*min\(\d+rem,\s*(\d+)%\)\s*;/,
  );
  assert.ok(floor, "the wrapper must reserve a minimum width for the disclosed prompt");
  const wrapperCaps = [...chatMessagesCss.matchAll(/\.user-message-wrapper\s*\{[^}]*?max-width:\s*(?:min\()?(\d+)%/g)].map(
    (match) => Number(match[1]),
  );
  assert.ok(wrapperCaps.length > 0, "the user-message wrapper must declare its percentage caps");
  assert.ok(
    wrapperCaps.every((cap) => Number(floor[1]) <= cap),
    "the minimum width must never exceed the wrapper's max-width at any breakpoint",
  );
  assert.match(
    chatMessagesCss,
    /\.user-message:has\(> \.task-prompt-disclosure\)\s*\{[^}]*?min-inline-size:\s*100%\s*;/,
    "the bubble must fill the reserved width",
  );
});
