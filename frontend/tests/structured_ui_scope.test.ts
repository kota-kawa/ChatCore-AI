import assert from "node:assert/strict";
import test from "node:test";

import {
  createStructuredUiMetricsScope,
  createStructuredUiStateScope,
  readStructuredUiScopeRoomId,
} from "../lib/chat_page/structured_ui_scope";

test("structured UI scopes encode delimiter-bearing ids without collisions", () => {
  const scope = createStructuredUiStateScope({
    loggedIn: true,
    roomMode: "normal",
    roomId: "room:with:colon",
    userScope: "user:42",
    answerId: "server:73",
    blockId: "report-ui",
  });

  assert.equal(scope, "user%3A42:room%3Awith%3Acolon:server%3A73:report-ui");
  assert.equal(readStructuredUiScopeRoomId(scope!), "room:with:colon");
  assert.equal(
    createStructuredUiMetricsScope("user:42", "room:with:colon", "normal"),
    "user%3A42:room%3Awith%3Acolon",
  );
});

test("guest and temporary chats have no persistent structured UI scope", () => {
  const base = { roomId: "room-1", answerId: "answer-1", blockId: "ui-1" };
  assert.equal(createStructuredUiStateScope({ ...base, loggedIn: false, roomMode: "normal", userScope: null }), undefined);
  assert.equal(createStructuredUiStateScope({ ...base, loggedIn: true, roomMode: "temporary", userScope: "user:42" }), undefined);
  assert.equal(createStructuredUiMetricsScope("user:42", "room-1", "temporary"), null);
  assert.equal(createStructuredUiMetricsScope("anonymous", "room-1", "normal"), null);
});
