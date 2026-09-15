import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const GUARD_IMPORT = "../public/static/css/base/form_zoom_guard.css";

const formZoomGuardCss = readFileSync(
  new URL("../public/static/css/base/form_zoom_guard.css", import.meta.url),
  "utf8",
);
const globalCss = readFileSync(
  new URL("../public/static/css/base/global.css", import.meta.url),
  "utf8",
);
const appTsx = readFileSync(new URL("../pages/_app.tsx", import.meta.url), "utf8");
const adminIndexTsx = readFileSync(new URL("../pages/admin/index.tsx", import.meta.url), "utf8");

function removeCssComments(css: string) {
  return css.replace(/\/\*[\s\S]*?\*\//g, "");
}

const guardRules = removeCssComments(formZoomGuardCss);

// iOS Safari は font-size が 16px 未満の入力欄にフォーカスするとページを自動拡大する。
// iOS Safari zooms the page whenever a control below 16px receives focus.
test("form zoom guard raises touch-device controls to at least 16px", () => {
  assert.match(
    guardRules,
    /@media\s*\(\s*pointer:\s*coarse\s*\)/,
    "the guard must only apply to touch devices",
  );

  const coarseBlock = guardRules.slice(guardRules.indexOf("@media"));

  assert.match(
    coarseBlock,
    /input[^{}]*,\s*textarea,\s*select\s*\{[^}]*font-size:\s*max\(\s*16px\s*,[^)]*\)\s*!important/,
    "input, textarea and select must all be floored at 16px inside the coarse-pointer block",
  );
});

// 既存のクラスセレクタ（詳細度 (0,2,0) まである）に勝つため、このファイルだけ !important を使う。
// This file alone uses !important so it can outrank existing class selectors.
test("form zoom guard keeps its declarations important", () => {
  const declarations = [...guardRules.matchAll(/font-size:[^;]+;/g)].map((match) => match[0]);

  assert.ok(declarations.length > 0, "the guard must declare a font-size");
  for (const declaration of declarations) {
    assert.match(
      declaration,
      /!important/,
      `every guard declaration must outrank class selectors: ${declaration}`,
    );
  }
});

// トグル系の input は拡大対象外。サイズを変えるとレイアウトが崩れるため。
// Toggle-style inputs stay out of scope because resizing them breaks layouts.
test("form zoom guard excludes controls that never trigger focus zoom", () => {
  const exclusions = /input:not\(([^)]*)\)/.exec(guardRules)?.[1] ?? "";

  for (const type of ["checkbox", "radio", "range", "color", "submit", "button", "reset", "file"]) {
    assert.ok(
      exclusions.includes(`[type="${type}"]`),
      `input[type="${type}"] must be excluded from the zoom guard`,
    );
  }
});

// デスクトップの見た目は変えない。ポインタ精細な環境向けの宣言を持ってはいけない。
// Desktop styling must stay untouched: no fine-pointer declarations here.
test("form zoom guard leaves fine-pointer devices alone", () => {
  assert.doesNotMatch(
    guardRules,
    /pointer:\s*fine/,
    "the guard must not declare anything for precise pointers",
  );

  const outsideMediaQuery = guardRules.slice(0, guardRules.indexOf("@media")).trim();
  assert.equal(outsideMediaQuery, "", "the guard must not declare rules outside the media query");
});

// カスケードは後勝ちなので、ガードは CSS import の最後でなければならない。
// The cascade is last-wins, so the guard has to be the final CSS import.
test("_app.tsx imports the zoom guard last among CSS imports", () => {
  assert.ok(appTsx.includes(`import "${GUARD_IMPORT}";`), "_app.tsx must import the zoom guard");

  const cssImports = [...appTsx.matchAll(/^import\s+"([^"]+\.css)";$/gm)].map((match) => match[1]);

  assert.ok(cssImports.length > 1, "expected _app.tsx to bundle the global CSS set");
  assert.equal(
    cssImports[cssImports.length - 1],
    GUARD_IMPORT,
    "the zoom guard must come after every other CSS import",
  );
});

// 16px より大きく作られた入力欄はガードで縮めないよう書き戻しているが、その値はページ CSS が
// 正本。ずれると「デスクトップだけ新しいサイズ、スマホだけ古いサイズ」という無音の食い違いになる。
// Controls deliberately larger than 16px are written back so the guard cannot shrink them, but the
// page stylesheet owns those values. A drift would silently leave touch devices on the old size.
test("the zoom guard write-backs match the sizes memo_form.css declares", () => {
  const memoFormCss = readFileSync(
    new URL("../public/memo/static/css/memo_form.css", import.meta.url),
    "utf8",
  );

  const writeBacks = [
    { selector: ".memo-quick-capture__title-input", source: /\.memo-quick-capture__title-input\s*\{[^}]*?font-size:\s*([^;]+);/ },
    { selector: ".memo-modal__title-input", source: /\.memo-modal__title-input\s*\{[^}]*?font-size:\s*([^;]+);/ },
  ];

  for (const { selector, source } of writeBacks) {
    const declared = source.exec(memoFormCss)?.[1]?.trim();
    assert.ok(declared, `memo_form.css must still declare a font-size for ${selector}`);

    const guarded = new RegExp(`${selector.replace(".", "\\.")}\\s*\\{[^}]*?font-size:\\s*max\\(\\s*16px\\s*,\\s*([^)]+)\\)`)
      .exec(guardRules)?.[1]
      ?.trim();
    assert.ok(guarded, `form_zoom_guard.css must write ${selector} back`);

    assert.equal(
      guarded,
      declared,
      `${selector}: the guard writes back ${guarded} but memo_form.css declares ${declared}`,
    );
  }
});

// 生成UIは iframe の別ドキュメントなので、グローバルCSSが届かない。同じ下限を srcDoc の
// ベースCSSにも持たせないと、生成されたフォームのタップで親ページごとズームする。
// The generated UI lives in a separate iframe document that global CSS never reaches, so the same
// floor has to be repeated in the srcDoc base CSS or tapping a generated form zooms the parent.
test("the sandbox srcDoc carries the same zoom floor", () => {
  const sandboxSource = readFileSync(
    new URL("../components/chat_page/sandbox_artifact_frame.tsx", import.meta.url),
    "utf8",
  );

  assert.match(
    sandboxSource,
    /@media \(pointer:coarse\)\{input:not\([^)]*\)[^{]*\{font-size:max\(16px,1em\)!important;\}\}/,
    "the sandbox base CSS must floor its controls at 16px on touch devices",
  );
});

// iOS の横向き自動文字拡大を抑止する。
// Suppress iOS' automatic text inflation in landscape.
test("global.css disables automatic text size adjustment", () => {
  const htmlRule = /\bhtml\s*\{[^}]*\}/g;
  const htmlRules = globalCss.match(htmlRule) ?? [];
  const joined = htmlRules.join("\n");

  assert.match(joined, /-webkit-text-size-adjust:\s*100%/, "iOS needs the prefixed property");
  assert.match(joined, /(?<!-)\btext-size-adjust:\s*100%/, "the standard property must be set too");
});

// admin ページは Tailwind の text-sm(14px) を使うが、要素セレクタのガードで救われる。
// The admin pages keep Tailwind's text-sm (14px); the element-level guard rescues them.
test("admin Tailwind inputs are covered by the global guard instead of local overrides", () => {
  assert.match(adminIndexTsx, /const inputClass =[\s\S]*?text-sm/, "admin inputs still use text-sm");

  const firstRuleSelector = guardRules.slice(guardRules.indexOf("@media")).split("{")[1] ?? "";

  assert.match(
    firstRuleSelector.trim(),
    /^input:not\(/,
    "the guard must start from a bare element selector so class-styled inputs are covered",
  );
});
