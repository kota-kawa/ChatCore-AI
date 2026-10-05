import assert from "node:assert/strict";
import test from "node:test";

import {
  continueListOnEnter,
  findTaskMarkers,
  indentLines,
  toggleLineFormat,
  toggleTaskMarker,
  type TextEdit,
} from "../lib/memo/list_editing";

function apply(value: string, edit: TextEdit | null) {
  assert.ok(edit, "an edit was expected");
  const next = value.slice(0, edit.start) + edit.text + value.slice(edit.end);
  return { value: next, caret: edit.selectionStart, selection: next.slice(edit.selectionStart, edit.selectionEnd) };
}

function enterAtEnd(value: string) {
  return apply(value, continueListOnEnter(value, value.length, value.length));
}

test("Enter continues bullets, checklists and numbered lists with the same marker", () => {
  assert.equal(enterAtEnd("- りんご").value, "- りんご\n- ");
  assert.equal(enterAtEnd("* a").value, "* a\n* ");
  assert.equal(enterAtEnd("- [x] 済み").value, "- [x] 済み\n- [ ] ");
  assert.equal(enterAtEnd("1. 一番").value, "1. 一番\n2. ");
  assert.equal(enterAtEnd("9) nine").value, "9) nine\n10) ");
  assert.equal(enterAtEnd("  - [ ] 入れ子").value, "  - [ ] 入れ子\n  - [ ] ");
  assert.equal(enterAtEnd("> - 引用の中").value, "> - 引用の中\n> - ");
});

test("Enter puts the caret after the new marker and splits a line in the middle", () => {
  const value = "- りんごみかん";
  const result = apply(value, continueListOnEnter(value, 5, 5));
  assert.equal(result.value, "- りんご\n- みかん");
  assert.equal(result.caret, "- りんご\n- ".length);
});

test("Enter on an empty item moves a nested item out one level and ends a top-level list", () => {
  assert.deepEqual(enterAtEnd("- a\n  - [ ] "), { value: "- a\n- [ ] ", caret: "- a\n- [ ] ".length, selection: "" });
  assert.deepEqual(enterAtEnd("- a\n- [ ] "), { value: "- a\n", caret: 4, selection: "" });
  assert.deepEqual(enterAtEnd("1. a\n2. "), { value: "1. a\n", caret: 5, selection: "" });
});

test("Enter is left to the browser outside a list, inside the marker and with a selection", () => {
  assert.equal(continueListOnEnter("ただの行", 4, 4), null);
  assert.equal(continueListOnEnter("- [ ] a", 3, 3), null);
  assert.equal(continueListOnEnter("- a", 2, 3), null);
  assert.equal(continueListOnEnter("-ハイフン始まり", 8, 8), null);
});

test("toggleLineFormat adds, swaps and removes the format of the caret line", () => {
  const plain = "一行目\nただの行";
  const caret = plain.length;
  const task = apply(plain, toggleLineFormat(plain, caret, caret, "task"));
  assert.equal(task.value, "一行目\n- [ ] ただの行");
  assert.equal(task.caret, task.value.length);

  const bullet = apply(task.value, toggleLineFormat(task.value, task.caret, task.caret, "bullet"));
  assert.equal(bullet.value, "一行目\n- ただの行");
  const heading = apply(bullet.value, toggleLineFormat(bullet.value, bullet.caret, bullet.caret, "heading"));
  assert.equal(heading.value, "一行目\n## ただの行");
  const removed = apply(heading.value, toggleLineFormat(heading.value, heading.caret, heading.caret, "heading"));
  assert.equal(removed.value, plain);
  assert.equal(removed.caret, plain.length);
});

test("toggleLineFormat formats every selected line, numbering them and skipping blank lines", () => {
  const value = "a\n\n  b\nc";
  const numbered = apply(value, toggleLineFormat(value, 0, value.length, "number"));
  assert.equal(numbered.value, "1. a\n\n  2. b\n3. c");
  assert.equal(numbered.selection, numbered.value);

  const cleared = apply(numbered.value, toggleLineFormat(numbered.value, 0, numbered.value.length, "number"));
  assert.equal(cleared.value, value);
});

test("toggleLineFormat does not treat a checklist as an already bulleted line", () => {
  const value = "- [ ] a";
  assert.equal(apply(value, toggleLineFormat(value, 7, 7, "bullet")).value, "- a");
});

test("indentLines indents and outdents the selected lines", () => {
  const value = "- a\n- b";
  const indented = apply(value, indentLines(value, value.length, value.length, 1));
  assert.equal(indented.value, "- a\n  - b");
  assert.equal(indented.caret, indented.value.length);
  assert.equal(apply(indented.value, indentLines(indented.value, 0, indented.value.length, -1)).value, value);
  assert.equal(indentLines(value, 0, 0, -1), null);
});

test("findTaskMarkers follows preview order and ignores fenced code", () => {
  const source = "- [ ] a\n```\n- [x] コードの中\n```\n1. [X] b\n  * [ ] c\n- [] 欄ではない\n> - [x] d";
  assert.deepEqual(findTaskMarkers(source).map((marker) => marker.checked), [false, true, false, true]);
});

test("toggleTaskMarker flips only the requested box", () => {
  const source = "- [ ] パスポート\n- [x] 常備薬\n  - [ ] 予備";
  assert.equal(toggleTaskMarker(source, 0, 3), "- [x] パスポート\n- [x] 常備薬\n  - [ ] 予備");
  assert.equal(toggleTaskMarker(source, 1, 3), "- [ ] パスポート\n- [ ] 常備薬\n  - [ ] 予備");
  assert.equal(toggleTaskMarker(source, 2, 3), "- [ ] パスポート\n- [x] 常備薬\n  - [x] 予備");
});

test("toggleTaskMarker refuses when the rendered boxes do not match the source", () => {
  assert.equal(toggleTaskMarker("- [ ] a", 0, 2), null);
  assert.equal(toggleTaskMarker("- [ ] a", 3, 1), null);
});
