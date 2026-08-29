import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const foundationCss = readFileSync(
  new URL("../public/prompt_share/static/css/pages/prompt_share.foundation.css", import.meta.url),
  "utf8",
);
const responsiveCss = readFileSync(
  new URL("../public/prompt_share/static/css/pages/prompt_share.responsive.css", import.meta.url),
  "utf8",
);

// ヘッダーはページ上部に貼り付くツールバー。body に overflow を付けると body が
// スクロールコンテナ扱いになり sticky が効かなくなるため、両方をまとめて守る。
// The header is a sticky toolbar; any overflow on body turns it into a scroll
// container and silently breaks the sticky positioning, so guard both together.
test("prompt share header stays sticky and body keeps no overflow that would break it", () => {
  assert.match(
    foundationCss,
    /\.prompts-header \{[^}]*position: sticky;/,
    "the prompt share header must stay pinned to the top of the viewport",
  );
  assert.doesNotMatch(
    foundationCss,
    /body\.prompt-share-page \{\s*overflow[^}]*\}/,
    "overflow on body.prompt-share-page would stop the sticky header from sticking",
  );
});

// 右上には user-icon（ログイン時）と「ログイン / 登録」ボタン（未ログイン時）が固定表示される。
// The top right is occupied by the user icon when signed in and the login button when signed out.
test("prompt share header reserves room for the fixed top-right controls", () => {
  assert.match(
    foundationCss,
    /--ps-header-safe-right:/,
    "the header must define a reserve width for the pinned top-right controls",
  );
  assert.match(
    foundationCss,
    /\.prompts-header--guest \{\s*--ps-header-safe-right:/,
    "guests need a wider reserve because the login button is wider than the avatar",
  );
  assert.match(
    foundationCss,
    /\.prompts-header__inner \{[^}]*padding-right: max\(/,
    "the reserve must collapse on wide viewports where the margins already clear the controls",
  );
});

// スマホでは2段に折り返し、1段目の高さで右上コントロールをよける。
// On phones the toolbar wraps into two rows and the first row clears the pinned control.
test("prompt share header wraps into two rows on phones", () => {
  assert.match(
    responsiveCss,
    /\.prompts-header \{\s*position: static;/,
    "the toolbar should not eat vertical space on phones",
  );
  assert.match(
    responsiveCss,
    /\.hero-brand \{[^}]*min-height: 42px;/,
    "the brand row must be tall enough that the search row clears the pinned control",
  );
});
