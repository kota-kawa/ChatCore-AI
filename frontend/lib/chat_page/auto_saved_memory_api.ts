// チャットから自動保存された記憶の取得クライアント。通知（「記憶しました」）の表示に使う読み取りだけを持ち、
// 取り消しは記憶の更新 API（lib/memo/context_api.ts の updateContextFact）をそのまま使う。
// hooks/chat_page/use_auto_saved_memories.ts から使われる。
// Client that loads the memories auto-saved from a chat, read-only, for the "remembered" notices. Undoing
// reuses the memory update API (updateContextFact in lib/memo/context_api.ts). Used by hooks/chat_page/use_auto_saved_memories.ts.

import { ContextAutoSavedFactResponseSchema } from "../../types/generated/api_schemas";
import { resilientFetch } from "../../scripts/core/resilient_fetch";
import { fetchJson, isRecord } from "../../scripts/core/runtime_validation";

// fetch の差し替え口。既定は resilientFetch で、テストでは別の実装を渡せる。
// Injection point for fetch: resilientFetch by default, replaceable in tests.
type FetchImpl = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

// 通知 1 件。取り消しには revision が要る。
// One notice; undoing needs the revision.
export type AutoSavedMemory = {
  id: number;
  messageId: number;
  title: string;
  revision: number;
};

export type AutoSavedMemoryList = {
  // 自動抽出が無効なら false。クライアントは回答後の取り直しをやめる。
  // False when auto-extraction is off; the client then stops re-fetching after answers.
  enabled: boolean;
  memories: AutoSavedMemory[];
};

// 応答を通知に使える形へ直す。形の崩れた 1 件は捨て、全体が読めなければ null にする。
// Turn the payload into notice data. A malformed item is dropped; an unreadable payload yields null.
export function normalizeAutoSavedMemoryList(payload: unknown): AutoSavedMemoryList | null {
  if (!isRecord(payload) || !Array.isArray(payload.facts)) return null;
  const memories: AutoSavedMemory[] = [];
  for (const rawFact of payload.facts) {
    const parsed = ContextAutoSavedFactResponseSchema.safeParse(rawFact);
    if (!parsed.success) continue;
    const { id, message_id: messageId, title, revision } = parsed.data;
    memories.push({ id, messageId, title, revision });
  }
  return { enabled: payload.enabled === true, memories };
}

// 指定した部屋で自動保存された有効な記憶を取る。サーバーが所有者で絞る。失敗（未ログイン・サーバーエラー・
// 想定外の形）は null で返し、呼び出し側は黙って何も出さない。通信自体の失敗は throw する。
// Load the active memories auto-saved in a room (the server scopes by owner). A failure (logged out,
// server error, unexpected shape) returns null so the caller shows nothing; a network failure throws.
export async function fetchAutoSavedMemories(
  roomId: string,
  fetchImpl: FetchImpl = resilientFetch,
): Promise<AutoSavedMemoryList | null> {
  const query = new URLSearchParams({ room_id: roomId });
  const { response, payload } = await fetchJson<unknown>(
    `/api/context-facts/auto-saved?${query.toString()}`,
    { credentials: "same-origin" },
    fetchImpl,
  );
  if (!response.ok) return null;
  return normalizeAutoSavedMemoryList(payload);
}
