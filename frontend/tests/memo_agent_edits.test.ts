import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { applyMemoEdits, readMemoEditStep, type MemoEditsFailure, type MemoTextEdit } from "../lib/memo/agent_edits";

// サーバーの apply_memo_edits と共有するケース表。{"repeat": s, "times": n} は s を n 回繰り返した文字列を表す
// Case table shared with apply_memo_edits on the server; {"repeat": s, "times": n} stands for s repeated n times
type CaseString = string | { repeat: string; times: number };
type EditCase = {
  name: string;
  body: CaseString;
  edits: { old_string: CaseString; new_string: CaseString }[];
  expected: { body: CaseString } | { failure: MemoEditsFailure };
};

const { cases } = JSON.parse(
  readFileSync(new URL("../../tests/fixtures/memo_agent_edit_cases.json", import.meta.url), "utf8"),
) as { cases: EditCase[] };

function expand(value: CaseString): string {
  return typeof value === "string" ? value : value.repeat.repeat(value.times);
}

test("the shared case table is not empty", () => {
  assert.ok(cases.length > 0);
});

for (const editCase of cases) {
  test(`applyMemoEdits ${editCase.name}`, () => {
    const edits: MemoTextEdit[] = editCase.edits.map((edit) => ({
      old_string: expand(edit.old_string),
      new_string: expand(edit.new_string),
    }));
    const result = applyMemoEdits(expand(editCase.body), edits);
    if ("body" in editCase.expected) {
      assert.deepEqual(result, { ok: true, body: expand(editCase.expected.body) });
    } else {
      assert.deepEqual(result, { ok: false, failure: editCase.expected.failure });
    }
  });
}

test("readMemoEditStep reads a partial edit with its title", () => {
  assert.deepEqual(
    readMemoEditStep({ edits: [{ old_string: "月曜日", new_string: "火曜日" }], title: "会議メモ" }),
    { ok: true, payload: { kind: "edits", edits: [{ old_string: "月曜日", new_string: "火曜日" }], title: "会議メモ" } },
  );
});

test("readMemoEditStep reads a full replacement and drops a blank title", () => {
  assert.deepEqual(
    readMemoEditStep({ content: "新しい本文", title: "  " }),
    { ok: true, payload: { kind: "content", content: "新しい本文", title: undefined } },
  );
});

test("readMemoEditStep requires exactly one of edits and content", () => {
  const edits = [{ old_string: "a", new_string: "b" }];
  assert.deepEqual(readMemoEditStep({ content: "本文", edits }), { ok: false, reason: "invalid" });
  assert.deepEqual(readMemoEditStep({ title: "題名だけ" }), { ok: false, reason: "invalid" });
  // null は未指定として扱う（サーバーの検証と同じ）
  // null counts as absent, as on the server
  assert.equal(readMemoEditStep({ content: null, edits }).ok, true);
});

test("readMemoEditStep rejects malformed edits and empty content", () => {
  assert.deepEqual(readMemoEditStep({ edits: [] }), { ok: false, reason: "invalid" });
  assert.deepEqual(readMemoEditStep({ edits: [{ old_string: "a" }] }), { ok: false, reason: "invalid" });
  assert.deepEqual(readMemoEditStep({ edits: "a" }), { ok: false, reason: "invalid" });
  assert.deepEqual(readMemoEditStep({ content: "   " }), { ok: false, reason: "empty" });
});
