import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const taskOrderCss = readFileSync(
  new URL("../public/static/css/pages/chat/tasks_order/tasks_order.css", import.meta.url),
  "utf8",
);

test("editable task cards retain vertical touch movement for pointer reordering", () => {
  const editableTaskRule = taskOrderCss.match(
    /:where\(body\.chat-page, \.chat-page-shell\) \.task-wrapper\.editable\s*\{([^}]*)\}/,
  );

  assert.ok(editableTaskRule, "editable task card styles must be present");
  assert.match(
    editableTaskRule[1] ?? "",
    /touch-action:\s*none\s*;/,
    "browser panning must not cancel vertical pointer drags while reordering",
  );
});
