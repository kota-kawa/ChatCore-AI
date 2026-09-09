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

const sharedModalCss = readFileSync(
  new URL("../public/static/css/components/modal_surface.css", import.meta.url),
  "utf8",
);

// モーダルは ModalShell で body 直下へ描かれる。ロック中はページ本体だけを止め、
// 開いているモーダルは操作できるままにする。
// Modals render under <body> via ModalShell: the lock stops the page itself and keeps
// the open modal interactive.
test("open modals stay interactive while the prompt-share page is modal-locked", () => {
  assert.match(
    promptShareFoundationCss,
    /body\.prompt-share-page\.ps-modal-open \.prompt-share-page > \*\s*\{\s*pointer-events:\s*none\s*;/,
    "the page content must be treated as locked background",
  );
  assert.match(
    promptShareFoundationCss,
    /body\.prompt-share-page\.ps-modal-open \.modal-base\.is-open\s*\{\s*pointer-events:\s*auto\s*;/,
    "the open modal must explicitly accept pointer input",
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

// 投稿モーダルの下端に貼り付くバーは持たない。送信アクションは入力欄の続きとして流す。
// The composer never pins a bar to the bottom: the submit action flows after the inputs.
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

// 詳細モーダルの見出しは上に貼り付けない（スマホで本文の縦幅を削るため）。
// 固定するのはタブ行と閉じるボタンだけで、それは共通モーダル面のヘッダーが担う。
// The detail title block is not pinned (on phones it eats the body's height); only the tab row
// and close button stay, and that is the shared modal header's job.
test("the detail modal's title block scrolls with the body instead of sticking", () => {
  const headerRule = promptShareModalCss.match(
    /\.prompt-detail-header\s*\{([\s\S]*?)\}/,
  );
  assert.ok(headerRule, "the detail modal must style its title block");
  assert.doesNotMatch(
    headerRule[1],
    /position:\s*(sticky|fixed)/,
    "the title block must not be pinned to the top of the modal",
  );
});

// モーダルの面は共通トークンで塗り、グラデーション・ぼかし・発光は持たない。
// The modal surface is painted with shared tokens and carries no gradients, blur or glow.
test("the prompt-share modal styles do not reintroduce decorative gradients or blur", () => {
  const modalSection = promptShareModalCss.slice(promptShareModalCss.indexOf("Prompt Share のモーダル"));
  assert.ok(modalSection.length > 0, "the prompt-share modal section must exist");
  assert.doesNotMatch(modalSection, /gradient\(/, "no gradients in the modal styles");
  assert.doesNotMatch(modalSection, /backdrop-filter/, "no backdrop blur in the modal styles");
  assert.doesNotMatch(promptShareModalCss, /\.post-modal\b/, "the legacy .post-modal shell must be gone");
  assert.match(sharedModalCss, /\.cc-modal__panel\s*\{[\s\S]*?background:\s*var\(--modal-surface\);/);
  assert.doesNotMatch(sharedModalCss, /gradient\(|backdrop-filter/, "the shared surface stays flat");
});

// Prompt Share から開く編集モーダルは、設定画面の緑ではなくページの青をトークン差し替えで使う。
// The edit modal opened from Prompt Share swaps in the page blue through tokens, not restyling.
test("the Prompt Share edit modal uses the page blue palette through tokens", () => {
  assert.match(
    promptShareModalCss,
    /\.prompt-share-modal,\s*\.prompt-share-edit-modal-scope\s*\{[\s\S]*?--modal-accent:\s*#1a5fd0;/,
  );
  assert.match(
    promptShareModalCss,
    /\.prompt-share-edit-modal-scope\s*\{[\s\S]*?--prompt-edit-accent:\s*var\(--modal-accent\);/,
  );
  assert.match(
    promptShareModalCss,
    /\[data-theme="dark"\] \.prompt-share-modal,\s*\[data-theme="dark"\] \.prompt-share-edit-modal-scope\s*\{[\s\S]*?--modal-accent:\s*#7ab4ff;/,
  );
});
