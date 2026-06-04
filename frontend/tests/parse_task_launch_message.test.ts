import assert from "node:assert/strict";
import test from "node:test";

import { parseTaskLaunchMessage } from "../lib/chat_page/task_utils";

test("parses a task-launch message with task name and setup info", () => {
  const parsed = parseTaskLaunchMessage("【タスク】ℹ️ 情報提供\n【状況・作業環境】〇〇について調べたい");
  assert.deepEqual(parsed, {
    taskName: "ℹ️ 情報提供",
    setupInfo: "〇〇について調べたい",
  });
});

test("parses a task-launch message without setup info", () => {
  const parsed = parseTaskLaunchMessage("【タスク】ℹ️ 情報提供");
  assert.deepEqual(parsed, { taskName: "ℹ️ 情報提供", setupInfo: "" });
});

test("captures multi-line setup info verbatim", () => {
  const parsed = parseTaskLaunchMessage("【タスク】要約\n【状況・作業環境】1行目\n2行目\n3行目");
  assert.equal(parsed?.setupInfo, "1行目\n2行目\n3行目");
});

test("parses the reload format (html-escaped with <br> joins) identically", () => {
  // services/chat_use_case.py stores user messages as html.escape(text).replace("\n", "<br>").
  const stored = "【タスク】ℹ️ 情報提供<br>【状況・作業環境】A &amp; B を &lt;比較&gt; したい";
  assert.deepEqual(parseTaskLaunchMessage(stored), {
    taskName: "ℹ️ 情報提供",
    setupInfo: "A & B を <比較> したい",
  });
});

test("fresh-send and reloaded text yield the same parse result", () => {
  const fresh = "【タスク】要約\n【状況・作業環境】1行目\n2行目";
  const reloaded = "【タスク】要約<br>【状況・作業環境】1行目<br>2行目";
  assert.deepEqual(parseTaskLaunchMessage(fresh), parseTaskLaunchMessage(reloaded));
});

test("returns null for non task-launch messages", () => {
  assert.equal(parseTaskLaunchMessage("普通のメッセージです"), null);
  assert.equal(parseTaskLaunchMessage(""), null);
  assert.equal(parseTaskLaunchMessage(null), null);
});
