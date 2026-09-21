import assert from "node:assert/strict";
import test from "node:test";

import { shouldBeginEditingFromClick } from "../lib/memo/detail_click_to_edit";

// 擬似要素: closest がマッチするか否かだけを再現する
// Stand-in element that only models whether closest() finds an interactive ancestor
function fakeTarget(matches: boolean) {
  return { closest: () => (matches ? ({} as Element) : null) } as unknown as EventTarget;
}

test("a plain click on preview text starts editing", () => {
  assert.equal(
    shouldBeginEditingFromClick({ target: fakeTarget(false), defaultPrevented: false, selectionCollapsed: true }),
    true,
  );
});

test("clicks on links or controls inside the preview keep their own behaviour", () => {
  assert.equal(
    shouldBeginEditingFromClick({ target: fakeTarget(true), defaultPrevented: false, selectionCollapsed: true }),
    false,
  );
  assert.equal(
    shouldBeginEditingFromClick({ target: fakeTarget(false), defaultPrevented: true, selectionCollapsed: true }),
    false,
  );
});

test("finishing a drag selection does not switch to the editor", () => {
  assert.equal(
    shouldBeginEditingFromClick({ target: fakeTarget(false), defaultPrevented: false, selectionCollapsed: false }),
    false,
  );
});

test("a target without closest() (text node / null) still counts as a plain click", () => {
  assert.equal(
    shouldBeginEditingFromClick({ target: null, defaultPrevented: false, selectionCollapsed: true }),
    true,
  );
});
