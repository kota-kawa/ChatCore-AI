import assert from "node:assert/strict";
import test from "node:test";

import { describeActionStep } from "../lib/chat_page/mini_chat_runtime";

test("describeActionStep exposes the command and parameters of a typed action", () => {
  const details = describeActionStep({
    action: "app_action",
    command: "prompt.search",
    args: { query: "メール返信" },
    risk: "low",
    description: "検索欄に入力して検索する",
  });

  assert.deepEqual(
    details.map((detail) => detail.label),
    ["種類", "コマンド", "パラメータ", "リスク"],
  );
  assert.equal(details[0].value, "操作");
  assert.equal(details[1].value, "prompt.search");
  assert.match(details[2].value, /"query": "メール返信"/);
  assert.equal(details[2].multiline, true);
});

test("describeActionStep exposes the selector and typed value of an input step", () => {
  const details = describeActionStep({
    action: "input",
    selector: "#searchInput",
    value: "メール返信",
    description: "検索欄に入力する",
  });

  const rows = new Map(details.map((detail) => [detail.label, detail.value]));
  assert.equal(rows.get("対象要素"), "#searchInput");
  assert.equal(rows.get("入力する値"), "メール返信");
  // No command/args on a raw DOM step, so those rows must be absent.
  assert.equal(rows.has("コマンド"), false);
  assert.equal(rows.has("パラメータ"), false);
});

test("describeActionStep exposes the destination of a navigate step", () => {
  const details = describeActionStep({
    action: "navigate",
    path: "/prompt_share",
    description: "プロンプト共有を開く",
  });

  const rows = new Map(details.map((detail) => [detail.label, detail.value]));
  assert.equal(rows.get("種類"), "移動");
  assert.equal(rows.get("移動先"), "/prompt_share");
});

test("describeActionStep exposes the replacement body and title of a memo_edit step", () => {
  const details = describeActionStep({
    action: "memo_edit",
    title: "会議メモ（修正版）",
    content: "修正後の本文です。",
    risk: "low",
    description: "誤字を直した本文へ置き換えます",
  });

  const rows = new Map(details.map((detail) => [detail.label, detail.value]));
  assert.equal(rows.get("種類"), "メモ編集");
  assert.equal(rows.get("新しいタイトル"), "会議メモ（修正版）");
  assert.equal(rows.get("編集後の本文"), "修正後の本文です。");
  assert.equal(details.find((detail) => detail.label === "編集後の本文")?.multiline, true);
});

test("describeActionStep renders check and wait specifics", () => {
  const checkRows = new Map(
    describeActionStep({ action: "check", selector: "#agree", checked: false, description: "チェックを外す" })
      .map((detail) => [detail.label, detail.value]),
  );
  assert.equal(checkRows.get("チェック"), "オフにする");

  const waitRows = new Map(
    describeActionStep({ action: "wait", timeout_ms: 1200, description: "表示を待つ" })
      .map((detail) => [detail.label, detail.value]),
  );
  assert.equal(waitRows.get("待機時間"), "1200 ミリ秒");
});

test("describeActionStep spells out risk levels that force a confirmation", () => {
  const rows = new Map(
    describeActionStep({ action: "app_action", command: "memo.save", risk: "medium", description: "メモを保存する" })
      .map((detail) => [detail.label, detail.value]),
  );

  assert.equal(rows.get("リスク"), "中（実行前に確認します）");
});
