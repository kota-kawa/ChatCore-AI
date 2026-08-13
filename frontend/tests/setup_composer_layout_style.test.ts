import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

// セットアップ画面の入力欄のレイアウト規約をまとめて固定する。
// 以前は mobile_setup_composer_actions_style / setup_temporary_toggle_placement_style
// に分かれていたが、スマホとデスクトップで構造を共通化したため1ファイルに統合した。
// Layout contract for the setup composer. This used to live in two files, one per
// breakpoint; desktop and mobile now share the same structure, so it is one file.
const setupCss = readFileSync(
  new URL("../public/static/css/pages/chat/setup.css", import.meta.url),
  "utf8",
);
const chatInputCss = readFileSync(
  new URL("../public/static/css/pages/chat/chat_input.css", import.meta.url),
  "utf8",
);

const mobileBreakpoint = "@media (max-width: 576px)";
const baseSetupCss = setupCss.slice(0, setupCss.indexOf(mobileBreakpoint));
const mobileSetupCss = setupCss.slice(setupCss.indexOf(mobileBreakpoint));
const baseChatInputCss = chatInputCss.slice(0, chatInputCss.indexOf(mobileBreakpoint));
const mobileChatInputCss = chatInputCss.slice(chatInputCss.indexOf(mobileBreakpoint));

// 操作ボタンを textarea に重ねると、内部スクロール中の本文がボタンの下へ潜る。
// それを避けるために右側へ余白を確保すると、その分だけ入力できない領域が生まれる。
// ボタンを本文の下の行へ出すことで、幅を最後まで本文に使えるようにしている。
// iOS では、内部スクロールする textarea に重ねた要素が背面へ回って消える問題もある。
// Overlaying the buttons on the textarea pushes scrolled text underneath them, and
// the gutter that prevents it is space the user cannot type into. Keeping the
// buttons in a row below the text frees the full width. It also avoids iOS
// painting controls beneath a textarea's native scrolling layer.
test("setup composer keeps its actions in a row below the text, not on top of it", () => {
  assert.match(
    baseSetupCss,
    /\.setup-info-input-area\s*\{[^}]*?display:\s*grid\s*;[^}]*?grid-template-columns:\s*minmax\(0,\s*1fr\)\s+52px\s+52px\s*;/,
    "the composer must lay its actions out in a dedicated row",
  );
  assert.match(
    baseSetupCss,
    /#setup-info\s*\{[^}]*?grid-column:\s*1\s*\/\s*-1\s*;/,
    "the textarea must occupy its own full-width grid row",
  );
  assert.match(
    baseSetupCss,
    /\.setup-info-input-area \.setup-send-btn\s*\{[^}]*?grid-column:\s*3\s*;/,
    "the send button belongs in the action row",
  );
  // クリップボタンは追加メニューのラッパーに包まれているため、列を占めるのはラッパー側。
  // The paperclip is wrapped by the add menu, so the wrapper is what occupies the column.
  assert.match(
    baseSetupCss,
    /\.setup-info-input-area \.setup-attach-menu\s*\{[^}]*?grid-column:\s*2\s*;/,
    "the attachment menu belongs in the action row",
  );
  assert.match(
    baseSetupCss,
    /\.setup-info-input-area \.chat-save-mode-control\s*\{[^}]*?grid-column:\s*1\s*;[^}]*?justify-self:\s*start\s*;/,
    "the temporary chat toggle sits at the left end of the action row",
  );

  for (const [name, css] of [
    ["send", baseSetupCss.match(/\.setup-info-input-area \.setup-send-btn\s*\{[^}]*\}/)?.[0]],
    ["attach", baseSetupCss.match(/\.setup-info-input-area \.setup-attach-menu\s*\{[^}]*\}/)?.[0]],
    [
      "toggle",
      baseSetupCss.match(/\.setup-info-input-area \.chat-save-mode-control\s*\{[^}]*\}/)?.[0],
    ],
  ] as const) {
    assert.ok(css, `the ${name} rule must exist`);
    assert.doesNotMatch(
      css,
      /position:\s*absolute/,
      `the ${name} control must not be overlaid on the textarea`,
    );
  }
});

// ボタンが重ならなくなったので、本文用の余白を右下に確保する必要はない。
// 以前は密度調整クラス（.setup-fit-compact / .setup-fit-tight）が
// padding-right: calc(1.84rem + 104px) を積んでおり、その幅は入力できなかった。
// With nothing overlapping the text, no gutter has to be reserved for it. The
// density classes used to add padding-right: calc(1.84rem + 104px), and that
// strip of the textarea could not be typed into.
test("setup textarea reserves no gutter for the action buttons", () => {
  assert.match(
    baseSetupCss,
    /#setup-info\s*\{[^}]*?padding:\s*var\(--setup-field-padding-y\)\s+0\s*;/,
    "the textarea must use the full width between the shell's inner edges",
  );
  assert.doesNotMatch(
    setupCss,
    /#setup-info\s*(,[^{]*)?\{[^}]*?padding-right:\s*calc\([^;]*104px/,
    "no breakpoint or density class may reserve overlay space inside the textarea",
  );
});

// textarea 自身の枠を消してシェルの枠だけを見せることで、本文と操作ボタンの
// 間の境界線をなくす。枠を消すとフォーカス表示も消えるため、シェルの
// :focus-within で必ず補う。シェルの配色は後続のブレークポイント/テーマ指定で
// 上書きされるので、フォーカス指定は詳細度で勝てる形（#setup-container 込み）
// になっている必要がある。
// Hiding the textarea's frame removes the seam between the text and the action
// buttons, but it also removes the focus indicator, so the shell's :focus-within
// restores it. Later breakpoint and theme rules restyle the shell, so the focus
// selector has to out-specify them (it includes #setup-container).
test("setup composer is one seamless field whose focus ring survives the cascade", () => {
  assert.match(
    baseSetupCss,
    /#setup-info\s*\{[^}]*?border-color:\s*transparent\s*;[^}]*?background:\s*transparent\s*;/,
    "the textarea must not draw its own frame inside the composer shell",
  );
  assert.match(
    baseSetupCss,
    /#setup-info:focus\s*\{[^}]*?border-color:\s*transparent\s*;/,
    "focusing the textarea must not bring the inner frame back",
  );
  assert.match(
    baseSetupCss,
    /\.setup-info-field-shell\s*\{[^}]*?border:\s*1px solid[^;]+;/,
    "the shell must draw the field's frame instead",
  );

  for (const [label, prefix] of [
    ["light", ""],
    ["dark", '\\[data-theme="dark"\\] '],
  ] as const) {
    const focusRule = new RegExp(
      `${prefix}:where\\(body\\.chat-page, \\.chat-page-shell\\) #setup-container \\.setup-info-field-shell:focus-within`,
    );
    // ダークの指定はライトのブレークポイント群より後ろにあるため、全文から探す
    // The dark rules live past the breakpoint blocks, so match against the whole file
    assert.match(
      setupCss,
      focusRule,
      `the ${label} focus ring must out-specify the later shell rules`,
    );
  }
});

// スマホは寸法だけを詰める。構造まで作り直すと、二重管理で片方だけ壊れる。
// Mobile only tightens the dimensions; rebuilding the structure per breakpoint
// would mean two copies to keep in sync.
test("mobile only narrows the shared composer layout", () => {
  assert.match(
    mobileSetupCss,
    /\.setup-info-input-area\s*\{[^}]*?grid-template-columns:\s*minmax\(0,\s*1fr\)\s+48px\s+48px\s*;/,
    "mobile must narrow the action columns to its 48px buttons",
  );
  assert.doesNotMatch(
    mobileSetupCss,
    /\.setup-info-input-area \.setup-(send|attach)-btn\s*\{[^}]*?position:\s*relative/,
    "mobile must not have to undo an overlay the base layout no longer creates",
  );
});

// トグルの高さが送信ボタンと違うと、操作行の下端がそろわない。
// A toggle of a different size would break the action row's baseline.
test("the temporary chat toggle matches the send button size at every breakpoint", () => {
  const sizeOf = (css: string, pattern: RegExp, what: string) => {
    const match = css.match(pattern);
    assert.ok(match, `the ${what} sizing rule must exist`);
    return {
      width: match[1].match(/(?:^|\s)width:\s*([^;]+);/)?.[1].trim(),
      height: match[1].match(/(?:^|\s)height:\s*([^;]+);/)?.[1].trim(),
    };
  };
  const sendSize = (css: string) =>
    sizeOf(
      css,
      /:where\(body\.chat-page, \.chat-page-shell\) \.setup-send-btn,[\s\S]*?\{([^}]*)\}/,
      "send button",
    );
  const toggleSize = (css: string) =>
    sizeOf(css, /\.chat-save-mode-toggle\s*\{([^}]*)\}/, "toggle");

  assert.deepEqual(toggleSize(baseSetupCss), sendSize(baseChatInputCss));
  assert.deepEqual(toggleSize(mobileSetupCss), sendSize(mobileChatInputCss));
});
