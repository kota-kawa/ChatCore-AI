import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const memoDetailModal = readFileSync(
  new URL("../components/memo/MemoDetailModal.tsx", import.meta.url),
  "utf8",
);
const memoCss = readFileSync(
  new URL("../public/memo/static/css/memo_form.css", import.meta.url),
  "utf8",
);

test("the memo detail modal omits the date and keeps the content switcher in the header", () => {
  assert.doesNotMatch(memoDetailModal, /formatDateTime|memo-modal__date/);

  const headerActionsStart = memoDetailModal.indexOf("memo-modal__header-actions");
  const bodyStart = memoDetailModal.indexOf("memo-modal__body");
  assert.ok(headerActionsStart >= 0, "the modal must have a header action row");
  assert.ok(bodyStart > headerActionsStart, "the body must follow the header action row");
  assert.match(
    memoDetailModal.slice(headerActionsStart, bodyStart),
    /memo-modal__tabs[\s\S]*role="tablist"/,
    "edit and preview controls must live in the header action row",
  );
  assert.doesNotMatch(
    memoDetailModal.slice(bodyStart),
    /memo-modal__tabs/,
    "the body must not spend vertical space on a separate tab row",
  );
});

test("the memo detail action row stays one line and scrolls horizontally on phones", () => {
  const mobileCss = memoCss.slice(memoCss.lastIndexOf("@media (max-width: 640px)"));
  const actionRule = mobileCss.match(/\.memo-modal \.memo-modal__header-actions\s*\{([\s\S]*?)\}/);
  assert.ok(actionRule, "the mobile memo action row must be styled");
  assert.match(actionRule[1], /flex-basis:\s*100%/);
  assert.match(actionRule[1], /overflow-x:\s*auto/);
  assert.match(actionRule[1], /scrollbar-width:\s*none/);

  const modeRule = memoCss.match(/\.memo-modal \.memo-modal__tabs\s*\{([\s\S]*?)\}/);
  assert.ok(modeRule, "the memo mode switcher must be styled as a compact control");
  assert.match(modeRule[1], /margin:\s*0/);
  assert.match(modeRule[1], /border-radius:\s*9px/);

  const bodyRule = memoCss.match(/\.memo-modal \.memo-modal__body\s*\{([\s\S]*?)\}/);
  assert.ok(bodyRule, "the memo body must keep a flex layout");
  assert.match(bodyRule[1], /overflow:\s*hidden/);
});
