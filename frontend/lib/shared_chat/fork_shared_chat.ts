import type { ChatRoomMode } from "../chat_page/types";
import { writeStoredActiveChatRoom, writeStoredHomePageViewState } from "../chat_page/storage";
import { extractApiErrorMessage, readJsonBodySafe } from "../../scripts/core/runtime_validation";
import { resilientFetch } from "../../scripts/core/resilient_fetch";

export type ForkedChatRoom = {
  id: string;
  mode: ChatRoomMode;
};

type ForkResponsePayload = {
  id?: unknown;
  mode?: unknown;
  error?: unknown;
};

// 複製先ルームのIDは既存のチャットルーム作成と同じ方式で採番する。
// Generate the target room id the same way the existing room creation flow does.
export function createForkedRoomId() {
  return Date.now().toString();
}

// 共有チャットを閲覧者自身のルームへ複製する。共有元は読み取り専用のまま変更されない。
// 失敗時はサーバーのエラーメッセージを持つ Error を投げる。
// Fork a shared chat into a room owned by the viewer; the source stays read-only.
// Throws an Error carrying the server's message when the fork fails.
export async function forkSharedChat(
  token: string,
  roomId: string,
  fallbackErrorMessage: string,
): Promise<ForkedChatRoom> {
  const response = await resilientFetch("/api/fork_shared_chat_room", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify({ token, id: roomId }),
  });

  const payload = (await readJsonBodySafe(response)) as ForkResponsePayload;
  const forkedRoomId = typeof payload.id === "string" ? payload.id : "";

  if (!response.ok || payload.error || !forkedRoomId) {
    // ステータスを渡すと本文のエラーが無いとき「サーバーエラー: N」になるため、
    // 2xx なのに本文が不正なケースでは渡さず、汎用の文言にフォールバックさせる。
    // Passing the status yields "server error: N" when the body carries no message, which is
    // misleading for a 2xx response with a malformed body — fall back to the generic message.
    throw new Error(
      extractApiErrorMessage(payload, fallbackErrorMessage, response.ok ? undefined : response.status),
    );
  }

  return {
    id: forkedRoomId,
    mode: payload.mode === "temporary" ? "temporary" : "normal",
  };
}

// チャット画面は localStorage から前回のビューとルームを復元するため、遷移前に
// 複製先ルームを「アクティブなチャット」として記録しておく。
// The chat view restores its last view and room from localStorage, so record the forked
// room as the active chat before navigating there.
export function rememberForkedChatRoom(room: ForkedChatRoom) {
  writeStoredActiveChatRoom(room.id, room.mode);
  writeStoredHomePageViewState("chat");
}
