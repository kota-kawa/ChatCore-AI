import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const setupCss = readFileSync(
  new URL("../public/static/css/pages/chat/setup.css", import.meta.url),
  "utf8",
);
const mobileBreakpoint = "@media (max-width: 576px)";
const desktopSetupCss = setupCss.slice(0, setupCss.indexOf(mobileBreakpoint));
const mobileSetupCss = setupCss.slice(setupCss.indexOf(mobileBreakpoint));

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

// 密度調整クラスは textarea の右下にボタン用の余白を確保するが、その前提は
// 「ボタンが textarea に重なっている」デスクトップの配置。スマホでは操作行が
// 分かれているので、余白を残すと入力できない死に領域になる。
// The density classes reserve room at the bottom-right of the textarea for the
// overlaying buttons. Mobile splits them into their own row, so leaving that
// reservation in place would waste area the user cannot type into.
test("mobile setup composer lets text use the whole textarea under the density classes", () => {
  for (const densityClass of ["setup-fit-compact", "setup-fit-tight"]) {
    assert.match(
      desktopSetupCss,
      new RegExp(
        `#setup-container\\.${densityClass} #setup-info\\s*\\{[^}]*?padding-right:\\s*calc\\(`,
        "s",
      ),
      `the ${densityClass} density still reserves overlay space on desktop`,
    );
    assert.match(
      mobileSetupCss,
      new RegExp(
        `#setup-container\\.${densityClass} #setup-info[^{]*\\{[^}]*?padding-right:\\s*var\\(--setup-field-padding-x\\)\\s*;[^}]*?padding-bottom:\\s*var\\(--setup-field-padding-y\\)\\s*;`,
        "s",
      ),
      `the mobile layout must clear the ${densityClass} overlay padding, matching its specificity`,
    );
  }
});
