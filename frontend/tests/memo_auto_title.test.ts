import assert from "node:assert/strict";
import test from "node:test";

import { autoMemoTitle, isAutoMemoTitle } from "../lib/memo/auto_title";

test("autoMemoTitle takes the first non-empty line, trimmed and capped like the server", () => {
  assert.equal(autoMemoTitle("\n  歯医者 10/12  \r\n2 行目"), "歯医者 10/12");
  assert.equal(autoMemoTitle("   \n"), "");
  assert.equal(autoMemoTitle("あ".repeat(300)).length, 255);
});

test("isAutoMemoTitle tells a derived title from one the user wrote", () => {
  assert.equal(isAutoMemoTitle("歯医者 10/12", "歯医者 10/12\n15:00"), true);
  assert.equal(isAutoMemoTitle("予定", "歯医者 10/12\n15:00"), false);
  assert.equal(isAutoMemoTitle("", ""), false);
  assert.equal(isAutoMemoTitle(undefined, "本文"), false);
});
