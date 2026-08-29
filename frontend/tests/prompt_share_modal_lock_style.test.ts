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

// ファイル選択後にプレビューが増えても、フォーカス中のinputがモーダル外へ移動しないようにする。
// Keep the focused file input anchored when the preview is inserted so the modal cannot jump-scroll.
test("the composer's image input and preview stay within the upload field width", () => {
  const uploadRule = promptShareModalCss.match(
    /\.image-upload-field\s*\{([\s\S]*?)\}/,
  );
  assert.ok(uploadRule, "the composer must style its image upload field");
  assert.match(uploadRule[1], /position:\s*relative;/);
  assert.match(uploadRule[1], /min-width:\s*0;/);
  assert.match(uploadRule[1], /overflow:\s*hidden;/);

  const inputRule = promptShareModalCss.match(
    /\.image-upload-field input\[type="file"\]\s*\{([\s\S]*?)\}/,
  );
  assert.ok(inputRule, "the file input must have a local, visually hidden position");
  assert.match(inputRule[1], /position:\s*absolute;/);
  assert.match(inputRule[1], /top:\s*0;/);
  assert.match(inputRule[1], /left:\s*0;/);

  const previewRule = promptShareModalCss.match(
    /\.prompt-image-preview\s*\{([\s\S]*?)\}/,
  );
  assert.ok(previewRule, "the composer must constrain the selected image preview");
  assert.match(previewRule[1], /min-width:\s*0;/);
  assert.match(previewRule[1], /max-width:\s*100%;/);
  assert.match(previewRule[1], /overflow:\s*hidden;/);

  const previewImageRule = promptShareModalCss.match(
    /\.prompt-image-preview img\s*\{([\s\S]*?)\}/,
  );
  assert.ok(previewImageRule, "the selected image must be constrained to the preview card");
  assert.match(previewImageRule[1], /max-width:\s*100%;/);
});

// 詳細モーダルのヘッダーは上に貼り付けない。特にスマホでは本文の縦幅を削ってしまうため。
// The detail modal's header must not be pinned: on phones it eats the body's height.
test("the detail modal's header scrolls with the body instead of sticking", () => {
  const headerRule = promptShareModalCss.match(
    /#promptDetailModal \.prompt-detail-header\s*\{([\s\S]*?)\}/,
  );
  assert.ok(headerRule, "the detail modal must style its header");
  assert.doesNotMatch(
    headerRule[1],
    /position:\s*(sticky|fixed)/,
    "the header must not be pinned to the top of the modal",
  );

  // 上端の色帯は持たない。カードやモーダルの端だけを塗るアクセントは使わない方針。
  // No accent rail on the top edge: colouring just one edge of a card or modal is out.
  assert.doesNotMatch(
    promptShareModalCss,
    /\.post-modal-content--(detail|composer)::before\s*\{/,
    "the detail and composer sheets must not draw a coloured rail on their top edge",
  );
});

// 閉じるボタンは他のモーダルと同じ丸ボタンを使う（詳細モーダル専用の角丸ボタンは持たない）
// The close button reuses the other modals' round button; no detail-only variant remains
test("the detail modal reuses the round close button shared with the other modals", () => {
  assert.doesNotMatch(promptShareModalCss, /\.prompt-detail-close\b/);
  assert.doesNotMatch(promptShareResponsiveCss, /\.prompt-detail-close\b/);
  assert.match(
    promptShareModalCss,
    /\.prompt-share-page \.close-btn\s*\{[\s\S]*?border-radius:\s*50%;/,
  );
});

// 固定されたコピー行が、右上の閉じるボタンの下へ潜り込まないだけの逃げを持つこと
// The stuck copy row must keep enough clearance to never sit under the close button
test("the sticky body header keeps clear of the close button", () => {
  const stickyRule = promptShareModalCss.match(
    /\.prompt-detail-section__header--sticky\s*\{([\s\S]*?)\}/,
  );
  assert.ok(stickyRule, "the body section must style its sticky header");

  const padding = stickyRule[1].match(/padding:\s*[\d.]+rem\s+([\d.]+)rem/);
  assert.ok(padding, "the sticky header must declare its horizontal padding");
  assert.ok(
    Number(padding[1]) >= 2.5,
    "the right padding must clear the 2.45rem close button",
  );
});

// Prompt Shareの編集モーダルは、設定画面の緑ではなくページ本体の青系で統一する。
// The Prompt Share edit modal uses the page's blue palette instead of the settings page green.
test("the Prompt Share edit modal uses the page blue palette", () => {
  assert.match(
    promptShareModalCss,
    /#promptEditModalScope\s*\{[\s\S]*?--prompt-edit-accent:\s*var\(--ps-primary/,
  );
  assert.match(
    promptShareModalCss,
    /#promptEditModalScope \.edit-prompt-modal__header\s*\{[\s\S]*?rgba\(var\(--prompt-edit-accent-rgb\),\s*0\.2\)/,
  );
  assert.match(
    promptShareModalCss,
    /#promptEditModalScope \.edit-prompt-modal__button--primary\s*\{[\s\S]*?linear-gradient\(135deg,\s*var\(--prompt-edit-accent\),\s*var\(--prompt-edit-accent-strong\)\)/,
  );
  assert.match(
    promptShareModalCss,
    /#promptEditModalScope \.prompt-category-select__option\.is-selected\s*\{[\s\S]*?linear-gradient\(135deg,\s*#3b8eff,\s*var\(--prompt-edit-accent-strong\)\)/,
  );
  assert.match(
    promptShareModalCss,
    /\[data-theme="dark"\] #promptEditModalScope\s*\{[\s\S]*?--prompt-edit-accent:\s*#60a5fa;/,
  );
});
