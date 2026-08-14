import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const promptShareFoundationCss = readFileSync(
  new URL("../public/prompt_share/static/css/pages/prompt_share.foundation.css", import.meta.url),
  "utf8",
);
const promptShareCardCss = readFileSync(
  new URL("../public/prompt_share/static/css/pages/prompt_share.cards-actions.css", import.meta.url),
  "utf8",
);
const promptShareModalCss = readFileSync(
  new URL("../public/prompt_share/static/css/pages/prompt_share.modals-composer.css", import.meta.url),
  "utf8",
);
const promptShareResponsiveCss = readFileSync(
  new URL("../public/prompt_share/static/css/pages/prompt_share.responsive.css", import.meta.url),
  "utf8",
);

// プロフィールモーダルは共通の背景操作ロックから除外し、モーダル自身は操作可能なままにする。
// The profile modal must be excluded from the page interaction lock and remain interactive itself.
test("author profile modal stays interactive while the prompt-share page is modal-locked", () => {
  assert.match(
    promptShareFoundationCss,
    /:not\(#promptAuthorProfileModal\)\s*\{\s*pointer-events:\s*none\s*;/,
    "the profile modal must not be treated as locked background content",
  );
  assert.match(
    promptShareFoundationCss,
    /#promptAuthorProfileModal\.show\s*\{\s*pointer-events:\s*auto\s*;/,
    "the open profile modal must explicitly accept pointer input",
  );
});

test("author names do not gain an underline on hover in cards or the detail modal", () => {
  assert.match(
    promptShareCardCss,
    /\.prompt-card__author:hover \.prompt-card__author-name\s*\{[\s\S]*?text-decoration:\s*none;/,
  );
  assert.match(
    promptShareModalCss,
    /\.prompt-detail-author:hover span\s*\{[\s\S]*?text-decoration:\s*none;/,
  );
});

// 作例画像は「見て確かめる」ための面なので、シートの縦幅を大きく使えるようにしておく。
// The example image is meant to be looked at, so it must keep a generous share of the sheet height.
test("the detail modal's example image keeps a large display height", () => {
  const imageRule = promptShareModalCss.match(
    /\.prompt-detail-media \.modal-reference-image img\s*\{([\s\S]*?)\}/,
  );
  assert.ok(imageRule, "the detail modal must style its example image");

  const maxHeight = imageRule[1].match(/max-height:\s*clamp\(\s*(\d+)px\s*,\s*(\d+)vh\s*,\s*(\d+)px\s*\)/);
  assert.ok(maxHeight, "the example image height must be a clamp() so it scales with the viewport");
  assert.ok(
    Number(maxHeight[1]) >= 200,
    "the smallest example image height must stay readable",
  );
  assert.ok(
    Number(maxHeight[2]) >= 40,
    "the example image must claim a large share of the viewport height",
  );
});

// 投稿モーダルの下端に貼り付くバーは廃止した。送信アクションは入力欄の続きとして流す。
// The composer no longer pins a bar to the bottom: the submit action flows after the inputs.
test("the composer's submit action is not pinned to the bottom of the modal", () => {
  assert.doesNotMatch(
    promptShareModalCss,
    /\.composer-footer\b/,
    "the sticky composer footer must be gone from the composer styles",
  );
  assert.doesNotMatch(
    promptShareResponsiveCss,
    /\.composer-footer\b/,
    "the sticky composer footer must be gone from the responsive styles",
  );

  const actionsRule = promptShareModalCss.match(/\.composer-actions\s*\{([\s\S]*?)\}/);
  assert.ok(actionsRule, "the composer must style its submit action row");
  assert.doesNotMatch(
    actionsRule[1],
    /position:\s*(sticky|fixed)/,
    "the submit action row must scroll with the form instead of sticking",
  );
});
