import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const setupCss = readFileSync(
  new URL("../public/static/css/pages/chat/setup.css", import.meta.url),
  "utf8",
);
const chatInputCss = readFileSync(
  new URL("../public/static/css/pages/chat/chat_input.css", import.meta.url),
  "utf8",
);

const mobileBreakpoint = "@media (max-width: 576px)";
const desktopSetupCss = setupCss.slice(0, setupCss.indexOf(mobileBreakpoint));
const mobileSetupCss = setupCss.slice(setupCss.indexOf(mobileBreakpoint));
const desktopChatInputCss = chatInputCss.slice(0, chatInputCss.indexOf(mobileBreakpoint));
const mobileChatInputCss = chatInputCss.slice(chatInputCss.indexOf(mobileBreakpoint));

// 一時保存（未保存チャット）トグルは送信・添付ボタンと同じ操作行の左端に置く。
// 高さがずれると3つのボタンの下端がそろわないため、送信ボタンの寸法と突き合わせる。
// The temporary-chat toggle belongs at the left end of the same action row as the
// attach/send buttons. Its box must match the send button so all three line up.
test("the temporary chat toggle sits at the left of the setup action row", () => {
  assert.match(
    desktopSetupCss,
    /\.setup-info-input-area \.chat-save-mode-control\s*\{[^}]*?position:\s*absolute\s*;[^}]*?left:\s*calc\(0\.72rem[^;]*;[^}]*?bottom:\s*calc\(0\.72rem[^;]*;/,
    "the toggle must be anchored to the bottom-left of the input area",
  );
  assert.match(
    desktopSetupCss,
    /\.setup-info-input-area \.setup-send-btn\s*\{[^}]*?bottom:\s*calc\(0\.72rem[^;]*;/,
    "the send button must keep the bottom offset the toggle is aligned to",
  );
  assert.doesNotMatch(
    desktopSetupCss,
    /\.chat-save-mode-control\s*\{[^}]*?top:/,
    "the toggle must no longer float in the top corner of the input shell",
  );
});

test("the temporary chat toggle matches the send button size at every breakpoint", () => {
  const sendButtonSize = (css: string) => {
    const match = css.match(
      /:where\(body\.chat-page, \.chat-page-shell\) \.setup-send-btn,[\s\S]*?\{([^}]*)\}/,
    );
    assert.ok(match, "the send button sizing rule must exist");
    return {
      width: match[1].match(/(?:^|\s)width:\s*([^;]+);/)?.[1].trim(),
      height: match[1].match(/(?:^|\s)height:\s*([^;]+);/)?.[1].trim(),
    };
  };
  const toggleSize = (css: string) => {
    const match = css.match(/\.chat-save-mode-toggle\s*\{([^}]*)\}/);
    assert.ok(match, "the toggle sizing rule must exist");
    return {
      width: match[1].match(/(?:^|\s)width:\s*([^;]+);/)?.[1].trim(),
      height: match[1].match(/(?:^|\s)height:\s*([^;]+);/)?.[1].trim(),
    };
  };

  assert.deepEqual(toggleSize(desktopSetupCss), sendButtonSize(desktopChatInputCss));
  assert.deepEqual(toggleSize(mobileSetupCss), sendButtonSize(mobileChatInputCss));
});

// スマホでは操作ボタンを textarea の外のグリッド行に分けている。トグルもその行に
// 加わる必要があり、左端の1カラム目に入る。
// Mobile keeps the actions in a grid row outside the textarea; the toggle joins
// that row in the first (left-most) column.
test("the mobile setup composer keeps the temporary chat toggle in the action row", () => {
  assert.match(
    mobileSetupCss,
    /\.setup-info-input-area \.chat-save-mode-control\s*\{[^}]*?position:\s*relative\s*;[^}]*?left:\s*auto\s*;[^}]*?bottom:\s*auto\s*;[^}]*?grid-column:\s*1\s*;/,
    "the toggle must share the action row instead of overlaying the textarea",
  );
});
