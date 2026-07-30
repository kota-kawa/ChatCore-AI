import assert from "node:assert/strict";
import test from "node:test";

import { formatUserInputForDisplay } from "../scripts/chat/chat_ui";

test("formatUserInputForDisplay does not render raw user HTML", () => {
  const html = formatUserInputForDisplay('<img src=x onerror=alert(1)> **hello**');

  assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.doesNotMatch(html, /<img/i);
  assert.match(html, /<strong>hello<\/strong>/);
});

test("formatUserInputForDisplay hides an internal task id from task launch messages", () => {
  const html = formatUserInputForDisplay(
    "【タスク】同名タスク\n【タスクID】42\n【状況・作業環境】通常本文を保持する",
  );

  assert.doesNotMatch(html, /タスクID|42/);
  assert.match(html, /同名タスク/);
  assert.match(html, /通常本文を保持する/);
});

test("formatUserInputForDisplay keeps a task-id-like line in ordinary user text", () => {
  const html = formatUserInputForDisplay("確認用メモ\n【タスクID】42\n通常本文");

  assert.match(html, /タスクID/);
  assert.match(html, /42/);
  assert.match(html, /通常本文/);
});
