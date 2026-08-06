import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import SharedChatPage from "../pages/shared/[token]";
import { LocaleProvider } from "../contexts/locale_context";

const basePayload = {
  room: { id: "room-1", title: "共有チャット", created_at: "2026-08-01T09:30:00+00:00" },
  messages: [
    { sender: "user", message: "こんにちは&lt;p&gt;", timestamp: "2026-08-01T09:30:10+00:00" },
    { sender: "assistant", message: "こんにちは。", timestamp: "2026-08-01T09:30:20+00:00" }
  ]
};

function renderSharedChatPage(payload: Record<string, unknown>) {
  return renderToStaticMarkup(
    React.createElement(LocaleProvider, {
      initialLocale: "ja",
      children: React.createElement(SharedChatPage, {
        payload,
        pageUrl: "https://chatcore-ai.com/shared/token",
        ogImageUrl: "https://chatcore-ai.com/static/og.jpg",
        token: "share-token"
      })
    })
  );
}

// 共有ページのメッセージは通常チャットと同じクラス構成で描画する必要がある。
// chat_messages.css は :where(body.chat-page, .chat-page-shell) 配下でしか効かないため、
// ルートの chat-page-shell とメッセージ側のクラスが揃って初めて同じ見た目になる。
// Shared chat messages must use the same class structure as the regular chat: chat_messages.css
// only applies under :where(body.chat-page, .chat-page-shell), so both parts are required.
test("shared chat page reuses the regular chat message markup", () => {
  const html = renderSharedChatPage(basePayload);

  assert.match(html, /class="shared-chat-page chat-page-shell"/);
  assert.match(html, /class="chat-message-row"/);
  assert.match(html, /class="message-wrapper user-message-wrapper"/);
  assert.match(html, /class="user-message"/);
  assert.match(html, /class="message-wrapper bot-message-wrapper"/);
  assert.match(html, /class="bot-message"/);
  assert.match(html, /class="bot-message-parts"/);
});

// 他ページと同じ右下メニューを共有ページにも出す。
// The shared page shows the same bottom-right action menu as the other pages.
test("shared chat page renders the shared bottom-right action menu", () => {
  const html = renderSharedChatPage(basePayload);

  assert.match(html, /<action-menu><\/action-menu>/);
});

// 共有ページからは「このチャットを続ける」で自分のチャットへ複製できる。
// The shared page offers "continue this chat", which forks the conversation into the viewer's own chat.
test("shared chat page offers a button to continue the conversation", () => {
  const html = renderSharedChatPage(basePayload);

  assert.match(html, /class="shared-chat-continue__button[^"]*"/);
  assert.match(html, /このチャットを続ける/);
  // 読み取り専用であること自体は引き続き明示する。
  // The read-only nature of the page is still stated explicitly.
  assert.match(html, /読み取り専用/);
});

// サーバー側では DOMPurify が使えず整形結果がエスケープされるため、ユーザー発言の
// HTML を SSR してはいけない（ハイドレーション不一致でタグが文字として残る）。
// User message HTML must not be server-rendered: DOMPurify is unavailable there, so the
// escaped output would survive hydration and show raw tags to the reader.
test("shared chat page does not server-render escaped user message HTML", () => {
  const html = renderSharedChatPage(basePayload);

  assert.ok(!html.includes("&amp;lt;p&amp;gt;"), "escaped markup must not be rendered on the server");
});

// エラー時は会話を描画せずエラーメッセージだけを表示する。
// On error the page shows only the error message and no conversation.
test("shared chat page renders only the error message when the fetch failed", () => {
  const html = renderSharedChatPage({ error: "共有リンクが見つかりませんでした。" });

  assert.match(html, /共有リンクが見つかりませんでした。/);
  assert.ok(!html.includes("chat-message-row"), "no message rows are rendered on the error page");
});
