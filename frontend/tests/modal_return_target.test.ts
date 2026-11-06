// カードへ戻る閉じ方の移動量・縮尺の計算を検証する。
// Tests the offset/scale math for closing a modal back into its card.

import assert from "node:assert/strict";
import test from "node:test";

import { computeModalReturnMotion, modalOriginKey } from "../lib/ui/modal_return_target";

const viewport = { width: 1280, height: 800 };
const panel = { left: 120, top: 40, width: 1040, height: 720 };

test("lays the panel's top-left corner and size over the card", () => {
  const card = { left: 300, top: 500, width: 260, height: 180 };
  assert.deepEqual(computeModalReturnMotion(panel, card, viewport), {
    x: 180,
    y: 460,
    scaleX: 0.25,
    scaleY: 0.25,
  });
});

test("returns null when the card is scrolled out of view, so the modal fades in place", () => {
  assert.equal(computeModalReturnMotion(panel, { left: 300, top: 900, width: 260, height: 180 }, viewport), null);
  assert.equal(computeModalReturnMotion(panel, { left: 300, top: -200, width: 260, height: 180 }, viewport), null);
});

test("returns null when the card or the panel has no size", () => {
  assert.equal(computeModalReturnMotion(panel, { left: 300, top: 200, width: 0, height: 0 }, viewport), null);
  assert.equal(
    computeModalReturnMotion({ left: 0, top: 0, width: 0, height: 0 }, { left: 300, top: 200, width: 260, height: 180 }, viewport),
    null,
  );
});

test("keeps a partly visible card as a target", () => {
  const card = { left: 300, top: 700, width: 260, height: 180 };
  assert.notEqual(computeModalReturnMotion(panel, card, viewport), null);
});

test("prefixes the kind so the same ID on different card types does not collide", () => {
  assert.equal(modalOriginKey("memo", 12), "memo:12");
  assert.notEqual(modalOriginKey("memo", 12), modalOriginKey("task", 12));
});

test("makes no marker for a card without a settled ID", () => {
  assert.equal(modalOriginKey("prompt", undefined), null);
  assert.equal(modalOriginKey("prompt", null), null);
  assert.equal(modalOriginKey("prompt", ""), null);
});
