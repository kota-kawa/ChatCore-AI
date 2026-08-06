import { memo, useEffect } from "react";

import { decodeStoredMessage, normalizeSharedSender } from "../../lib/shared_chat/message_text";
import type { SharedChatMessage } from "../../lib/shared_chat/types";
import { initCodeBlockCopyButtons } from "../../scripts/chat/chat_ui";
import { SharedChatMessageParts } from "./shared_chat_message_parts";
import { SharedChatUserMessage } from "./shared_chat_user_message";

type SharedChatMessageListProps = {
  emptyLabel: string;
  messages: SharedChatMessage[];
};

// 共有チャットのメッセージ一覧。通常チャット（chat_message_list.tsx）と同じ
// クラス構成（.chat-message-row / .message-wrapper / .user-message / .bot-message）で
// 描画するため、chat_messages.css の見た目がそのまま適用される。
// Read-only message list for shared chats. It reuses the exact class structure of the regular
// chat message list, so chat_messages.css styles it identically without duplicated CSS.
function SharedChatMessageListComponent({ emptyLabel, messages }: SharedChatMessageListProps) {
  // コードブロックのコピーボタンは document 委譲で動くため、共有ページでも初期化する。
  // The code block copy buttons rely on a delegated document listener, so initialise it here too.
  useEffect(() => {
    initCodeBlockCopyButtons();
  }, []);

  if (messages.length === 0) {
    return <p className="shared-chat-empty">{emptyLabel}</p>;
  }

  return (
    <>
      {messages.map((message, index) => {
        const sender = normalizeSharedSender(message.sender);
        const decoded = decodeStoredMessage(message.message || "");
        const rowKey = `${sender}-${index}-${message.timestamp || ""}`;

        if (sender === "user") {
          return (
            <div key={rowKey} className="chat-message-row">
              <div className="message-wrapper user-message-wrapper">
                <div className="user-message">
                  <SharedChatUserMessage text={decoded} />
                </div>
              </div>
            </div>
          );
        }

        return (
          <div key={rowKey} className="chat-message-row">
            <div className="message-wrapper bot-message-wrapper">
              <div className="bot-message">
                <SharedChatMessageParts fallbackText={decoded} parts={message.message_parts} />
              </div>
            </div>
          </div>
        );
      })}
    </>
  );
}

// 不要な再レンダリングを防ぐためにメモ化する
// Memoized to prevent unnecessary re-renders
export const SharedChatMessageList = memo(SharedChatMessageListComponent);
SharedChatMessageList.displayName = "SharedChatMessageList";
