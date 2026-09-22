import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const memoDetailModal = readFileSync(
  new URL("../components/memo/MemoDetailModal.tsx", import.meta.url),
  "utf8",
);
const memoCss = readFileSync(
  new URL("../public/memo/static/css/memo_form.css", import.meta.url),
  "utf8",
);
const globalCss = readFileSync(
  new URL("../public/static/css/base/global.css", import.meta.url),
  "utf8",
);

test("the memo detail modal omits the date and keeps the content switcher in the header", () => {
  assert.doesNotMatch(memoDetailModal, /formatDateTime|memo-modal__date/);

  const headerActionsStart = memoDetailModal.indexOf("memo-modal__header-actions");
  const bodyStart = memoDetailModal.indexOf("memo-modal__body");
  assert.ok(headerActionsStart >= 0, "the modal must have a header action row");
  assert.ok(bodyStart > headerActionsStart, "the body must follow the header action row");
  assert.match(
    memoDetailModal.slice(headerActionsStart, bodyStart),
    /memo-modal__tabs[\s\S]*role="tablist"/,
    "edit and preview controls must live in the header action row",
  );
  assert.doesNotMatch(
    memoDetailModal.slice(bodyStart),
    /memo-modal__tabs/,
    "the body must not spend vertical space on a separate tab row",
  );
});

test("the memo detail action row stays one line and scrolls horizontally on phones", () => {
  const mobileCss = memoCss.slice(memoCss.lastIndexOf("@media (max-width: 640px)"));
  const actionRule = mobileCss.match(/\.memo-modal \.memo-modal__header-actions\s*\{([\s\S]*?)\}/);
  assert.ok(actionRule, "the mobile memo action row must be styled");
  assert.match(actionRule[1], /flex-basis:\s*100%/);
  assert.match(actionRule[1], /overflow-x:\s*auto/);
  assert.match(actionRule[1], /scrollbar-width:\s*none/);

  const modeRule = memoCss.match(/\.memo-modal \.memo-modal__tabs\s*\{([\s\S]*?)\}/);
  assert.ok(modeRule, "the memo mode switcher must be styled as a compact control");
  assert.match(modeRule[1], /margin:\s*0/);
  assert.match(modeRule[1], /border-radius:\s*9px/);

  const bodyRule = memoCss.match(/\.memo-modal \.memo-modal__body\s*\{([\s\S]*?)\}/);
  assert.ok(bodyRule, "the memo body must keep a flex layout");
  assert.match(bodyRule[1], /overflow:\s*hidden/);
});

test("a coloured memo paints the whole detail modal surface, not just a band", () => {
  const accentRule = memoCss.match(/\.memo-modal__content\.has-accent\s*\{([\s\S]*?)\}/);
  assert.ok(accentRule, "the accented detail panel must be styled");
  assert.match(
    accentRule[1],
    /background:\s*var\(--memo-detail-color\)/,
    "the panel surface must take the memo's colour instead of the default white",
  );
  assert.match(
    accentRule[1],
    /--modal-surface:\s*color-mix\([^;]*var\(--memo-detail-color\)/,
    "controls on the coloured panel must sit on a lighter mix of the same colour",
  );
  assert.match(accentRule[1], /--modal-text:\s*#202124/, "the coloured panel keeps dark text in both themes");

  assert.doesNotMatch(
    memoCss,
    /\.memo-modal__content\.has-accent \.memo-modal__header::before/,
    "the thin colour band is redundant once the whole surface carries the colour",
  );
});

// メモエージェントは MiniChat の表示オプションを既定と違う形で使う。使ったオプションの分だけ
// パネル側の CSS が必要で、無いと補足が素のまま出て崩れる。
// The memo agent renders MiniChat with display options that need matching panel styles.
test("the memo agent panel styles every MiniChat option it turns on", () => {
  const agentPanel = memoDetailModal.slice(memoDetailModal.indexOf("memo-modal__agent-panel"));
  const scope = "\\.memo-modal \\.memo-modal__agent-panel ";

  // トップページのチャコと同じアイコンのみの会話クリア / Icon-only clear control, matching Chaco on the home page
  assert.match(agentPanel, /iconOnlyClearButton=\{true\}/);
  assert.match(
    memoCss,
    new RegExp(`${scope}\\.mini-chat-clear-btn--icon-only\\s*\\{[\\s\\S]*?width:\\s*34px`),
    "the icon-only clear control must stay a compact square",
  );
  assert.doesNotMatch(
    memoCss,
    new RegExp(`${scope}\\.mini-chat-clear-btn\\s*\\{`),
    "the memo panel must not add styles for a labelled clear control",
  );

  // 使用モデルの表示 / The model label
  assert.match(agentPanel, /showModelLabel/);
  const modelRule = memoCss.match(new RegExp(`${scope}\\.mini-chat-model-label\\s*\\{([\\s\\S]*?)\\}`));
  assert.ok(modelRule, "the model label must be styled as a caption, not as body text");
  assert.match(modelRule[1], /font-size:\s*0\.7rem/);
  assert.match(modelRule[1], /color:\s*var\(--modal-text-muted\)/);

  // 会話上限の注意書きは MiniChat が常に出しうる / MiniChat can always show the context notice
  const noticeRule = memoCss.match(new RegExp(`${scope}\\.mini-chat-context-notice\\s*\\{([\\s\\S]*?)\\}`));
  assert.ok(noticeRule, "the context notice must be styled");
  assert.match(noticeRule[1], /background:\s*var\(--modal-surface-muted\)/);
});

// メモ本文は overflow: hidden で、スクロールするのは内側のプレビュー面 / textarea。
// 本文側に右パディングやガターが残るとバーがパネル端から浮き、本文自身がスクロールする
// 他のモーダル（.cc-modal__body）と見た目がずれる。
// The memo body is overflow: hidden and the inner preview pane / textarea scrolls. Right
// padding or a reserved gutter on the body pushes the bar away from the panel edge that every
// other modal (.cc-modal__body, which scrolls itself) puts it on.
test("the memo detail scrollbar sits on the panel edge like every other modal", () => {
  const gutterRule = globalCss.match(/:where\(([^)]*)\)\s*\{\s*scrollbar-gutter:\s*stable;\s*\}/);
  assert.ok(gutterRule, "base/global.css must keep its shared scrollbar-gutter list");
  assert.doesNotMatch(
    gutterRule[1],
    /\.memo-modal__body/,
    "the memo body never scrolls, so a stable gutter there only reserves a strip no bar fills",
  );

  const singlePanePadding = memoCss.match(
    /\.memo-modal \.memo-modal__body:not\(\.memo-modal__body--with-agent\)\s*\{([\s\S]*?)\}/,
  );
  assert.ok(singlePanePadding, "the single-pane body must drop its right padding");
  assert.match(singlePanePadding[1], /padding-right:\s*0/);

  for (const pane of ["memo-modal__edit-textarea", "memo-modal__preview-pane"]) {
    assert.match(
      memoCss,
      new RegExp(
        `\\.memo-modal__body:not\\(\\.memo-modal__body--with-agent\\) \\.${pane}[\\s\\S]*?padding-right:`,
      ),
      `the right padding must move onto .${pane}, which is what actually scrolls`,
    );
  }

  // 読む面と書く面でバーの見た目が変わらないこと（textarea は global.css の既定だと軌道に色が付く）
  // Reading and editing must show the same bar (the global.css textarea default paints the track)
  const textareaRule = memoCss.match(/\.memo-modal \.memo-modal__edit-textarea\s*\{([\s\S]*?)\}/);
  const previewRule = memoCss.match(/\.memo-modal \.memo-modal__preview-pane\s*\{([\s\S]*?)\}/);
  assert.ok(textareaRule && previewRule, "both memo panes must be styled");
  for (const rule of [textareaRule[1], previewRule[1]]) {
    assert.match(rule, /scrollbar-color:\s*var\(--scrollbar-thumb\) transparent/);
  }

  // エージェント面を縦積みにする幅では本文自身がスクロール側に変わるので、そこは溝を確保する
  // At the width that stacks the agent panel the body becomes the scroller, so it keeps a gutter
  const stackedCss = memoCss.slice(memoCss.indexOf("@media (max-width: 1120px)"));
  const stackedRule = stackedCss.match(/\.memo-modal \.memo-modal__body--with-agent\s*\{([\s\S]*?)\}/);
  assert.ok(stackedRule, "the stacked agent layout must be styled");
  assert.match(stackedRule[1], /overflow-y:\s*auto/);
  assert.match(stackedRule[1], /scrollbar-gutter:\s*stable/);
});
