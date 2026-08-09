import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const setupCss = readFileSync(
  new URL("../public/static/css/pages/chat/setup.css", import.meta.url),
  "utf8",
);
const mobileSetupCss = setupCss.slice(setupCss.indexOf("@media (max-width: 576px)"));

// 長文入力時、iOS の textarea は独立したスクロール描画層になる。操作ボタンを
// その上へ絶対配置すると背面に隠れるため、スマホでは別のグリッド行へ分離する。
// A long textarea uses a native scrolling layer on iOS. Mobile actions must live
// in a separate grid row instead of being absolutely overlaid on that layer.
test("mobile setup composer keeps attachment and send actions outside the textarea", () => {
  assert.match(
    mobileSetupCss,
    /\.setup-info-input-area\s*\{[^}]*?display:\s*grid\s*;[^}]*?grid-template-columns:\s*minmax\(0,\s*1fr\)\s+48px\s+48px\s*;/,
    "the mobile setup composer must reserve a separate row for both actions",
  );
  assert.match(
    mobileSetupCss,
    /#setup-info\s*\{[^}]*?grid-column:\s*1\s*\/\s*-1\s*;/,
    "the textarea must occupy its own full-width grid row",
  );
  assert.match(
    mobileSetupCss,
    /\.setup-info-input-area \.setup-send-btn\s*\{[^}]*?position:\s*relative\s*;[^}]*?right:\s*auto\s*;[^}]*?bottom:\s*auto\s*;[^}]*?grid-column:\s*3\s*;/,
    "the send button must remain in the action row rather than overlaying the textarea",
  );
  assert.match(
    mobileSetupCss,
    /\.setup-info-input-area \.setup-attach-btn\s*\{[^}]*?position:\s*relative\s*;[^}]*?right:\s*auto\s*;[^}]*?bottom:\s*auto\s*;[^}]*?grid-column:\s*2\s*;/,
    "the attachment button must remain in the action row rather than overlaying the textarea",
  );
});
