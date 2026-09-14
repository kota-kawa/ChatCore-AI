import assert from "node:assert/strict";
import test from "node:test";

import {
  clampModalPosition,
  keepPositionIfUnchanged,
  positionModalAwayFromRect,
} from "../lib/ui/draggable_modal_position";

test("clampModalPosition resolves a mobile position before the modal is shown", () => {
  assert.deepEqual(
    clampModalPosition(
      { x: 20, y: 100 },
      { width: 351, height: 560 },
      { left: 0, top: 0, width: 375, height: 568 },
    ),
    { x: 12, y: 12 },
  );
});

test("clampModalPosition follows Visual Viewport offsets", () => {
  assert.deepEqual(
    clampModalPosition(
      { x: 0, y: 0 },
      { width: 360, height: 520 },
      { left: 8, top: 120, width: 390, height: 600 },
    ),
    { x: 20, y: 132 },
  );
});

test("positionModalAwayFromRect keeps the launcher clear on desktop", () => {
  const position = positionModalAwayFromRect(
    { x: 20, y: 100 },
    { width: 392, height: 620 },
    { left: 0, top: 0, width: 1366, height: 768 },
    { left: 40, top: 668, right: 100, bottom: 728 },
  );

  assert.deepEqual(position, { x: 20, y: 36 });
  assert.ok(position.y + 620 <= 668 - 12);
});

test("positionModalAwayFromRect uses the launcher's side when there is not enough height", () => {
  const position = positionModalAwayFromRect(
    { x: 20, y: 100 },
    { width: 392, height: 620 },
    { left: 0, top: 0, width: 700, height: 650 },
    { left: 40, top: 550, right: 100, bottom: 610 },
  );

  assert.equal(position.x, 112);
  assert.ok(position.x >= 100 + 12);
});

test("positionModalAwayFromRect preserves a safe stored position", () => {
  assert.deepEqual(
    positionModalAwayFromRect(
      { x: 600, y: 100 },
      { width: 392, height: 620 },
      { left: 0, top: 0, width: 1366, height: 768 },
      { left: 40, top: 668, right: 100, bottom: 728 },
    ),
    { x: 600, y: 100 },
  );
});

test("keepPositionIfUnchanged preserves the state object for resize bursts", () => {
  const current = { x: 12, y: 12 };

  assert.equal(keepPositionIfUnchanged(current, { x: 12, y: 12 }), current);
  assert.notEqual(keepPositionIfUnchanged(current, { x: 20, y: 12 }), current);
});
