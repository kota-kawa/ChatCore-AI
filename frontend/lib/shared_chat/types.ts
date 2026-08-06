import type { ChatMessagePart } from "../chat_page/types";

// 共有チャットの個別メッセージを表す型
// Represents a single message in a shared chat
export type SharedChatMessage = {
  message: string;
  message_parts?: ChatMessagePart[];
  sender: "user" | "assistant" | string;
  timestamp?: string;
};

// 共有チャットルームのメタ情報を表す型
// Represents metadata for a shared chat room
export type SharedChatRoom = {
  id: string;
  title?: string;
  created_at?: string;
};

// バックエンドから取得した共有チャット全体のペイロード型
// Top-level payload returned from the shared chat API
export type SharedChatPayload = {
  room?: SharedChatRoom;
  messages?: SharedChatMessage[];
  error?: string;
};
