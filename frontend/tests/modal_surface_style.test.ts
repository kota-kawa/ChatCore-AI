// 共通モーダル面の閉じる動きと ModalShell の待ち時間の対応を検証する。
// Tests that the shared modal surface's closing motion matches ModalShell's exit timer.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const modalSurfaceCss = readFileSync(new URL("../public/static/css/components/modal_surface.css", import.meta.url), "utf8");
const modalShellSource = readFileSync(new URL("../components/ui/modal_shell.tsx", import.meta.url), "utf8");

function ruleBody(css: string, selector: string) {
  const start = css.indexOf(`${selector} {`);
  assert.notEqual(start, -1, `${selector} is defined`);
  return css.slice(start, css.indexOf("}", start));
}

test("the closing animation lasts exactly as long as ModalShell keeps the closing phase", () => {
  const exitMs = Number(/MODAL_EXIT_DURATION_MS = (\d+);/.exec(modalShellSource)?.[1]);
  const cssMs = Number(/--cc-modal-exit-duration: (\d+)ms;/.exec(modalSurfaceCss)?.[1]);
  assert.ok(exitMs > 0);
  // CSS が短いと消えた面が残り、長いと動きの途中で途切れる
  // A shorter CSS duration leaves a finished surface on screen; a longer one cuts the motion off
  assert.equal(cssMs, exitMs);
});

test("the closing surface stays laid out but lets clicks through to the page", () => {
  const closing = ruleBody(modalSurfaceCss, ".cc-modal.is-closing");
  assert.match(closing, /display: flex;/);
  assert.match(closing, /pointer-events: none;/);
});

test("the backdrop fades its colour, not its opacity, so the panel keeps its own fade", () => {
  const overlayOut = ruleBody(modalSurfaceCss, "@keyframes cc-modal-overlay-out");
  assert.match(overlayOut, /background-color: transparent/);
  assert.doesNotMatch(overlayOut, /opacity/);
});

test("reduced motion closes at once instead of animating", () => {
  const reduced = modalSurfaceCss.slice(modalSurfaceCss.lastIndexOf("@media (prefers-reduced-motion: reduce)"));
  assert.match(reduced, /\.cc-modal\.is-closing \{\s*display: none;/);
});
