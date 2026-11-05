// 共有チャットのメッセージ本文を表示用に整える小さな関数。
// Small helpers that prepare shared chat message text for display.
// Used by components/shared_chat/shared_chat_message_list.tsx.

// DBに保存されたHTMLエスケープ済み文字列を表示用プレーンテキストに戻す
// Reverses HTML entity encoding so stored messages render correctly
export function decodeStoredMessage(raw: string) {
  return raw
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'");
}

// "user" 以外の送信者はすべて "assistant" として扱う
// Treat any sender value other than "user" as "assistant"
export function normalizeSharedSender(sender: string) {
  return sender === "user" ? "user" : "assistant";
}
