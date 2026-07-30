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
