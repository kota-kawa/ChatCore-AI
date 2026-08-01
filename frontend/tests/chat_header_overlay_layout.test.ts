import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const chatLayoutCss = readFileSync(
  new URL("../public/static/css/pages/chat/chat_layout.css", import.meta.url),
  "utf8",
);
const chatMessagesCss = readFileSync(
  new URL("../public/static/css/pages/chat/chat_messages.css", import.meta.url),
  "utf8",
);

// ヘッダーは帯として行を占有せず会話面の上に浮かぶ。これが崩れるとコンテナ上端の
// 領域が再び死に、会話の表示行数が減る。
// The header floats over the conversation instead of occupying a layout row. If this
// regresses, the top of the container becomes dead space again.
test("the chat header floats over the conversation instead of taking a row", () => {
  assert.match(
    chatLayoutCss,
    /\.chat-header\s*\{[^}]*?position:\s*absolute\s*;[^}]*?top:\s*0\s*;/,
    "the header must be pinned to the top of #chat-container as an overlay",
  );
  assert.match(
    chatLayoutCss,
    /#chat-container\s*\{[^}]*?position:\s*relative\s*;/,
    "#chat-container must be the containing block for the floating header",
  );
  assert.match(
    chatLayoutCss,
    /\.sidebar\s*\{\s*margin-top:\s*var\(--chat-header-height[^)]*\);\s*\}/,
    "the sidebar must start below the header instead of sliding under it",
  );
});

// 透明な帯がクリックを飲み込むと、その裏のメッセージが選択もクリックもできなくなる。
// グループ単位で戻すと、モバイルで flex: 1 に伸びる .header-left が
// サイドバー開閉ボタンのクリックまで奪う。
// A transparent band that keeps pointer events would swallow clicks meant for the
// messages underneath it — and restoring them per group lets .header-left (flex: 1 on
// mobile) steal clicks from the sidebar toggle floating below it.
test("only the header controls themselves capture pointer events", () => {
  assert.match(
    chatLayoutCss,
    /\.chat-header\s*\{[^}]*?pointer-events:\s*none\s*;/,
    "the transparent header band must let clicks through to the messages",
  );
  assert.match(
    chatLayoutCss,
    /\.chat-header :is\(button, \.chat-header-model-menu\)\s*\{\s*pointer-events:\s*auto\s*;\s*\}/,
    "only buttons and the open model menu may re-enable pointer events, and with a "
      + "class-only selector so #chat-container[data-view=\"setup\"] * still wins while the chat is hidden",
  );
});

// フェード距離がヘッダーの高さと一致していないと、ヘッダーの裏の文字がボタンと
// 重なって読めなくなる（短い場合）か、先頭メッセージが薄く見える（長い場合）。
// The fade must end exactly at the header's bottom edge: a shorter fade leaves text
// tangled with the buttons, a longer one dims the first message.
test("the message list's top fade is driven by the header height", () => {
  assert.match(
    chatMessagesCss,
    /--chat-fade-top:\s*var\(--chat-header-height[^)]*\);/,
    "the fade distance must follow the header height",
  );
  assert.match(
    chatMessagesCss,
    /\.chat-message-row--first\s*\{\s*padding-top:\s*calc\(var\(--chat-fade-top[^)]*\)\s*\+/,
    "the first row must clear the fade distance so it stays fully opaque at the top",
  );
  assert.doesNotMatch(
    chatMessagesCss.slice(chatMessagesCss.indexOf("@media (max-width: 992px)")),
    /\.chat-message-row--first\s*\{\s*padding-top:\s*[\d.]+rem/,
    "breakpoints must not pin the top spacing to a literal that ignores the header height",
  );
});
