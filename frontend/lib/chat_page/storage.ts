// チャット画面がブラウザの localStorage に持つ状態（会話の表示キャッシュ、生成の途中経過、直前に開いていたルーム、ビュー状態）の読み書き。
// 一時チャットの本文は端末に残さず、ユーザー切り替え時は前の利用者の状態を破棄する。
// Reads and writes the chat state kept in localStorage: the display cache of conversations, in-flight generation state,
// the last active room, and the home view state. Temporary chats never persist their text, and a user switch wipes the previous user's state.
// Used by hooks/chat_page/use_home_page_controller.ts, use_home_page_generation_actions.ts and lib/auth/account_switcher.ts.

import { STORAGE_KEYS, AUTH_SUCCESS_HINT } from "../../scripts/core/constants";
import { normalizeChatMessageParts } from "./api_contract";
import { getStreamingGenerativeUiDisplayText } from "./generative_ui_stream";
import { parseJsonText } from "../../scripts/core/runtime_validation";
import { clearCachedUserIconProfile } from "../../scripts/core/user_icon_cache";
import { clearPersistentCache } from "../data/persistent_cache";
import {
  clearAllCachedHistory,
  readCachedHistory,
  removeCachedHistory,
  writeCachedHistory,
  type HistoryCacheWriteResult,
} from "./history_cache";
import type { ChatRoomMode, ChatSender, StoredGenerationState, StoredHistoryEntry } from "./types";

// 生成の途中経過の保存期限。これより古いものは復元せず捨てる。
// Retention limit for saved in-flight generation state; older entries are discarded instead of restored.
const GENERATION_STATE_TTL_MS = 30 * 60 * 1000;
const GENERATION_STATE_KEY_PREFIX = "chatGeneration_";

// ログアウトを経由しないユーザー切り替え（別アカウントでの再ログインなど）から、
// 直前の利用者の永続状態を守るための「持ち主」マーカー。
// Marks who this browser's persisted chat state currently belongs to, so a user
// switch that skips logout does not leak the previous user's persisted state.
const USER_SCOPE_KEY = "chatcore.chat.userScope";
const ANONYMOUS_USER_SCOPE = "anonymous";

// ホーム画面の復元先。setup は新規チャットの設定画面、chat は会話画面。
// Which home view to restore: setup is the new-chat setup screen, chat is the conversation screen.
export type StoredHomePageViewState = "setup" | "chat";
// 書き込み時だけ "launching"（タスク起動中）も受け付け、保存では chat として扱う。
// Writes also accept "launching" (a task is being launched), which is stored as chat.
type WritableHomePageViewState = StoredHomePageViewState | "launching";

export type StoredActiveChatRoom = {
  roomId: string;
  roomMode: ChatRoomMode;
};

// 生成の途中経過を保存する、ルームごとの localStorage キー。
// Per-room localStorage key under which in-flight generation state is saved.
function getStoredGenerationKey(roomId: string) {
  return `${GENERATION_STATE_KEY_PREFIX}${roomId}`;
}

function normalizeStoredRoomMode(rawMode: unknown): ChatRoomMode {
  return rawMode === "temporary" ? "temporary" : "normal";
}

function normalizeStoredHomePageViewState(rawState: unknown): StoredHomePageViewState {
  return rawState === "chat" ? "chat" : "setup";
}

// リロード時に会話画面へ戻すか。保存済みのビューが chat か、生成が進行中のときに true。
// Whether to return to the conversation view on reload: true when the saved view is chat or a generation is in progress.
export function shouldRestoreHomeChatView(): boolean {
  try {
    if (normalizeStoredHomePageViewState(localStorage.getItem(STORAGE_KEYS.homePageViewState)) === "chat") {
      return true;
    }

    return readActiveStoredGenerationState() !== null;
  } catch {
    return false;
  }
}

export function readRestorableHomePageViewState(): StoredHomePageViewState {
  return shouldRestoreHomeChatView() ? "chat" : "setup";
}

export function writeStoredHomePageViewState(viewState: WritableHomePageViewState): boolean {
  try {
    localStorage.setItem(
      STORAGE_KEYS.homePageViewState,
      viewState === "setup" ? "setup" : "chat",
    );
    return true;
  } catch {
    return false;
  }
}

// 前回開いていたルームを読む。新しいキーが無いときだけ、旧キー（currentChatRoomId）にフォールバックする。
// Reads the room that was open last time; falls back to the legacy key (currentChatRoomId) only when the new key is absent.
export function readStoredActiveChatRoom(): StoredActiveChatRoom | null {
  try {
    const activeRoomId = localStorage.getItem(STORAGE_KEYS.activeChatRoomId)?.trim();
    if (activeRoomId) {
      return {
        roomId: activeRoomId,
        roomMode: normalizeStoredRoomMode(localStorage.getItem(STORAGE_KEYS.activeChatRoomMode)),
      };
    }

    const legacyRoomId = localStorage.getItem(STORAGE_KEYS.currentChatRoomId)?.trim();
    if (!legacyRoomId) return null;
    return {
      roomId: legacyRoomId,
      roomMode: "normal",
    };
  } catch {
    return null;
  }
}

// 開いているルームを保存する。null なら関連キーをすべて消す。一時チャットは旧キーへ書かず、通常チャットだけが旧キーにも残る。
// Saves the open room; null removes all related keys. Temporary chats are not written to the legacy key, only normal chats are.
export function writeStoredActiveChatRoom(roomId: string | null, mode: ChatRoomMode = "normal"): boolean {
  try {
    if (!roomId) {
      localStorage.removeItem(STORAGE_KEYS.activeChatRoomId);
      localStorage.removeItem(STORAGE_KEYS.activeChatRoomMode);
      localStorage.removeItem(STORAGE_KEYS.currentChatRoomId);
      return true;
    }

    const roomMode = normalizeStoredRoomMode(mode);
    localStorage.setItem(STORAGE_KEYS.activeChatRoomId, roomId);
    localStorage.setItem(STORAGE_KEYS.activeChatRoomMode, roomMode);

    if (roomMode === "temporary") {
      localStorage.removeItem(STORAGE_KEYS.currentChatRoomId);
    } else {
      localStorage.setItem(STORAGE_KEYS.currentChatRoomId, roomId);
    }

    return true;
  } catch {
    return false;
  }
}

// 履歴キャッシュへ書き込んだ結果（保存できたか、容量の都合で切り詰めたか、残した件数など）。
// Result of writing to the history cache (whether it was stored, truncated for capacity, how many entries were kept).
export type StoredHistoryWriteResult = HistoryCacheWriteResult;

// 「一時チャット」は本文を端末に残さないという約束の機能なので、書き込みは
// 一律スキップし、既存キャッシュが残っていれば消す。呼び出し側で分岐を
// 覚えておかなくて済むよう、ガードはここに集約する。
// "Temporary chat" promises never to leave its text on the device, so every
// write here is skipped outright, and any pre-existing cache entry for the
// room is dropped. The guard lives here so callers do not each need to
// remember the branch.
function skippedTemporaryWrite(roomId: string, droppedEntries: number): StoredHistoryWriteResult {
  removeCachedHistory(roomId);
  return {
    stored: true,
    truncated: false,
    retainedEntries: 0,
    droppedEntries,
  };
}

// ルームの表示キャッシュを読み、壊れた項目を除いて正規化する。失敗したら空配列を返す。
// Reads a room's display cache and normalizes it, dropping malformed entries; returns an empty array on failure.
export function readStoredHistory(roomId: string): StoredHistoryEntry[] {
  try {
    const raw = readCachedHistory(roomId);
    const parsed = raw ? parseJsonText(raw) : [];
    if (!Array.isArray(parsed)) return [];

    const normalized: StoredHistoryEntry[] = [];
    parsed.forEach((entry) => {
      if (!entry || typeof entry !== "object") return;
      const text = typeof (entry as { text?: unknown }).text === "string" ? (entry as { text: string }).text : "";
      const sender =
        typeof (entry as { sender?: unknown }).sender === "string"
          ? (entry as { sender: string }).sender
          : "assistant";
      const displayText = sender === "user" ? text : getStreamingGenerativeUiDisplayText(text);
      // 生成UIなどのパーツは保存時に書き込まれている。読み戻しで捨てると、リロード後に
      // Artifact が本文だけの吹き出しへ退化する。サーバーと同じ正規化を通して復元する。
      // Parts such as a generated UI are already written on save. Dropping them on read made
      // a reloaded artifact collapse into a text-only bubble, so they are restored through the
      // same normalization the server payloads use.
      const parts = normalizeChatMessageParts((entry as { parts?: unknown }).parts, undefined, sender !== "user");
      normalized.push({ text: displayText, sender, ...(parts?.length ? { parts } : {}) });
    });

    return normalized;
  } catch {
    return [];
  }
}

// ルームの表示キャッシュを丸ごと書き換える。一時チャットでは何も保存しない。
// Overwrites a room's display cache; temporary chats store nothing.
export function writeStoredHistory(
  roomId: string,
  entries: StoredHistoryEntry[],
  roomMode: ChatRoomMode = "normal",
): StoredHistoryWriteResult {
  if (roomMode === "temporary") return skippedTemporaryWrite(roomId, entries.length);
  return writeCachedHistory(roomId, entries);
}

// 既存のキャッシュの末尾へ 1 件足して保存する。一時チャットでは何も保存しない。
// Appends one entry to the existing cache; temporary chats store nothing.
export function appendStoredHistory(
  roomId: string,
  entry: StoredHistoryEntry,
  roomMode: ChatRoomMode = "normal",
): StoredHistoryWriteResult {
  if (roomMode === "temporary") return skippedTemporaryWrite(roomId, 1);
  const existing = readStoredHistory(roomId);
  return writeStoredHistory(roomId, [...existing, entry]);
}

// 送信できなかった発話を表示キャッシュからも取り消す。末尾が一致するときだけ削除し、
// 並行して届いた別の書き込みを巻き戻さないようにする。
// Undo a message that could not be sent from the display cache. It only removes
// the entry when the tail still matches, so a concurrent write is never rewound.
export function removeLastStoredHistoryEntry(
  roomId: string,
  entry: StoredHistoryEntry,
): StoredHistoryWriteResult | null {
  const existing = readStoredHistory(roomId);
  const last = existing[existing.length - 1];
  if (!last || last.sender !== entry.sender || last.text !== entry.text) return null;
  return writeStoredHistory(roomId, existing.slice(0, -1));
}

// 古い履歴を読み足したとき、既存のキャッシュの先頭へ追加して保存する。一時チャットでは何も保存しない。
// Prepends entries (older history loaded later) to the existing cache; temporary chats store nothing.
export function prependStoredHistory(
  roomId: string,
  entries: StoredHistoryEntry[],
  roomMode: ChatRoomMode = "normal",
): StoredHistoryWriteResult {
  if (roomMode === "temporary") return skippedTemporaryWrite(roomId, entries.length);
  const existing = readStoredHistory(roomId);
  return writeStoredHistory(roomId, [...entries, ...existing]);
}

// ルームの表示キャッシュと生成の途中経過をまとめて消す。
// Removes both a room's display cache and its in-flight generation state.
export function removeStoredHistory(roomId: string) {
  removeCachedHistory(roomId);
  clearStoredGenerationState(roomId);
}

// localStorage から読んだ値を検証して StoredGenerationState にする。roomId が無い、または保存期限を過ぎていれば null。
// Validates a value read from localStorage into a StoredGenerationState; null if roomId is missing or the retention limit has passed.
function normalizeStoredGenerationState(raw: unknown): StoredGenerationState | null {
  if (!raw || typeof raw !== "object") return null;
  const record = raw as {
    roomId?: unknown;
    roomMode?: unknown;
    generationId?: unknown;
    lastEventId?: unknown;
    streamedText?: unknown;
    updatedAt?: unknown;
  };

  if (typeof record.roomId !== "string" || !record.roomId.trim()) return null;
  const roomMode: ChatRoomMode = record.roomMode === "temporary" ? "temporary" : "normal";
  const lastEventId =
    typeof record.lastEventId === "number" && Number.isFinite(record.lastEventId) && record.lastEventId > 0
      ? Math.floor(record.lastEventId)
      : 0;
  const streamedText = typeof record.streamedText === "string" ? record.streamedText : "";
  const updatedAt =
    typeof record.updatedAt === "number" && Number.isFinite(record.updatedAt) ? record.updatedAt : 0;

  if (Date.now() - updatedAt > GENERATION_STATE_TTL_MS) return null;

  return {
    roomId: record.roomId,
    roomMode,
    ...(typeof record.generationId === "string" && record.generationId.trim()
      ? { generationId: record.generationId }
      : {}),
    lastEventId,
    streamedText,
    updatedAt,
  };
}

// ルームの生成の途中経過を読む。壊れている、期限切れ、別ルームのものなら、キーを削除して null を返す。
// Reads a room's in-flight generation state; removes the key and returns null if it is broken, expired, or belongs to another room.
export function readStoredGenerationState(roomId: string): StoredGenerationState | null {
  try {
    const raw = localStorage.getItem(getStoredGenerationKey(roomId));
    const parsed = raw ? parseJsonText(raw) : null;
    const normalized = normalizeStoredGenerationState(parsed);
    if (!normalized || normalized.roomId !== roomId) {
      if (raw) localStorage.removeItem(getStoredGenerationKey(roomId));
      return null;
    }
    return normalized;
  } catch {
    return null;
  }
}

// 生成の途中経過をルームごとのキーと「進行中の生成」キーの両方へ保存する。保存のたびに updatedAt を現在時刻に更新する。
// Saves in-flight generation state under both the per-room key and the active-generation key, refreshing updatedAt on every write.
export function writeStoredGenerationState(state: StoredGenerationState): boolean {
  const normalized = normalizeStoredGenerationState({
    ...state,
    updatedAt: Date.now(),
  });
  if (!normalized) return false;

  // 一時チャットの生成途中テキストも本文なので永続化しない。以前のスキップ前に
  // 書かれた値が残っていれば、ここで消す。
  // A temporary chat's in-flight generated text is still message content, so it is
  // never persisted. Drop anything written before this guard existed.
  if (normalized.roomMode === "temporary") {
    clearStoredGenerationState(normalized.roomId);
    return true;
  }

  try {
    const serialized = JSON.stringify(normalized);
    localStorage.setItem(getStoredGenerationKey(normalized.roomId), serialized);
    localStorage.setItem(STORAGE_KEYS.activeChatGeneration, serialized);
    return true;
  } catch {
    return false;
  }
}

// 保存済みの生成状態の一部（受信済みイベント ID・本文・生成 ID）だけを更新する。保存済みが無ければ何もしない。
// Updates only part of the saved generation state (last event id, text, generation id); does nothing if none is saved.
export function updateStoredGenerationState(
  roomId: string,
  updates: Partial<Pick<StoredGenerationState, "lastEventId" | "streamedText" | "generationId">>,
): boolean {
  const existing = readStoredGenerationState(roomId);
  if (!existing) return false;

  return writeStoredGenerationState({
    ...existing,
    ...updates,
  });
}

// 生成状態を消す。expected を渡すと、保存されている generationId が一致するときだけ消し、後から始まった別の生成の状態を巻き込まない。
// Clears generation state; with expected, only when the saved generationId matches, so a later generation's state is not wiped.
export function clearStoredGenerationState(roomId: string, expected?: { generationId?: string }) {
  if (expected && readStoredGenerationState(roomId)?.generationId !== expected.generationId) return;
  try {
    localStorage.removeItem(getStoredGenerationKey(roomId));
    const active = normalizeStoredGenerationState(
      parseJsonText(localStorage.getItem(STORAGE_KEYS.activeChatGeneration) || "null"),
    );
    if (!active || active.roomId === roomId) {
      localStorage.removeItem(STORAGE_KEYS.activeChatGeneration);
    }
  } catch {
    // localStorage の失敗は無視する
    // ignore localStorage failures
  }
}

// 「進行中の生成」キーが指すルームの生成状態を読む。キーが壊れていれば削除して null を返す。
// Reads the generation state of the room the active-generation key points to; removes the key and returns null if it is broken.
export function readActiveStoredGenerationState(): StoredGenerationState | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEYS.activeChatGeneration);
    const active = normalizeStoredGenerationState(raw ? parseJsonText(raw) : null);
    if (!active) {
      if (raw) localStorage.removeItem(STORAGE_KEYS.activeChatGeneration);
      return null;
    }
    return readStoredGenerationState(active.roomId);
  } catch {
    return null;
  }
}

// ログアウト、またはユーザー切り替え検知時に、この端末に残る本文・進行状態・
// 下書きを一括で消す。チャット全文の chatHistory_*／chatGeneration_* に加え、
// 復元経路が読む activeRoomId 系・ホーム画面のビュー状態・タスクキャッシュ・
// セットアップ下書きも対象にする。
// Wipe every locally persisted chat body, in-flight state and draft on this
// device, whether triggered by logout or a detected user switch. Covers the
// full chat text (chatHistory_*/chatGeneration_*) plus the active-room
// pointer, home view state, task cache and the setup draft the restore path
// reads.
export function clearAllHomePagePersistedState() {
  try {
    clearAllCachedHistory();
  } catch {
    // localStorage の失敗は無視する
    // ignore localStorage failures
  }

  try {
    for (let indexPosition = localStorage.length - 1; indexPosition >= 0; indexPosition -= 1) {
      const key = localStorage.key(indexPosition);
      if (!key) continue;
      if (key.startsWith(GENERATION_STATE_KEY_PREFIX) || key.startsWith(STORAGE_KEYS.tasksCachePrefix)) {
        localStorage.removeItem(key);
      }
    }
  } catch {
    // localStorage の失敗は無視する
    // ignore localStorage failures
  }

  try {
    localStorage.removeItem(STORAGE_KEYS.activeChatRoomId);
    localStorage.removeItem(STORAGE_KEYS.activeChatRoomMode);
    localStorage.removeItem(STORAGE_KEYS.currentChatRoomId);
    localStorage.removeItem(STORAGE_KEYS.activeChatGeneration);
    localStorage.removeItem(STORAGE_KEYS.homePageViewState);
    localStorage.removeItem(STORAGE_KEYS.setupInfoDraft);
    localStorage.removeItem(STORAGE_KEYS.memoComposeDraft);
  } catch {
    // localStorage の失敗は無視する
    // ignore localStorage failures
  }
}

// ユーザー ID を持ち主マーカーの値にする。ID が空なら未ログイン用の "anonymous"。
// Turns a user id into the owner-marker value; an empty id becomes "anonymous" for signed-out users.
function normalizeUserScopeValue(userId: string | null): string {
  const trimmed = typeof userId === "string" ? userId.trim() : "";
  return trimmed ? `user:${trimmed}` : ANONYMOUS_USER_SCOPE;
}

export function readStoredUserScope(): string | null {
  try {
    return localStorage.getItem(USER_SCOPE_KEY);
  } catch {
    return null;
  }
}

export function clearStoredUserScope() {
  try {
    localStorage.removeItem(USER_SCOPE_KEY);
  } catch {
    // localStorage の失敗は無視する
    // ignore localStorage failures
  }
}

// 保存済みの永続状態が「今確認できた利用者」のものか検証し、食い違っていれば
// 一括破棄する。ログアウトを経由しないユーザー切り替え（別アカウントでの
// 再ログインなど）から、直前の利用者の本文を守るための最後の砦。
// スコープが未記録（初回訪問など）の場合は、破棄せずそのまま記録するだけにする。
// Validate the persisted state against the just-confirmed user and wipe it all
// on a mismatch. This is the last line of defense against a user switch that
// skips logout (re-login as a different account, etc.). When no scope has
// been recorded yet (a fresh browser, for example) there is nothing to
// protect against, so it is simply recorded.
export function reconcileStoredUserScope(userId: string | null): { changed: boolean } {
  const nextScope = normalizeUserScopeValue(userId);
  const previousScope = readStoredUserScope();

  if (previousScope !== null && previousScope !== nextScope) {
    clearAllHomePagePersistedState();
    try {
      localStorage.setItem(USER_SCOPE_KEY, nextScope);
    } catch {
      // localStorage の失敗は無視する
      // ignore localStorage failures
    }
    return { changed: true };
  }

  if (previousScope === null) {
    try {
      localStorage.setItem(USER_SCOPE_KEY, nextScope);
    } catch {
      // localStorage の失敗は無視する
      // ignore localStorage failures
    }
  }

  return { changed: false };
}

// 履歴 API の sender を ChatSender に直す。user と thinking 以外はすべて assistant として扱う。
// Maps a history API sender to ChatSender; anything other than user and thinking is treated as assistant.
export function normalizeHistorySender(sender: string | undefined): ChatSender {
  if (sender === "user") return "user";
  if (sender === "thinking") return "thinking";
  return "assistant";
}

// 保存用の sender 名に変換する。アシスタント側は "bot" として書く（読み戻しは normalizeStoredSender）。
// Converts to the sender name used for storage; the assistant side is written as "bot" (read back by normalizeStoredSender).
export function toStoredSender(sender: ChatSender): string {
  if (sender === "user") return "user";
  return "bot";
}

export function normalizeStoredSender(sender: string): ChatSender {
  return sender === "user" ? "user" : "assistant";
}

// 認証状態キャッシュはトップページ以外（メモなど）とも共有するため
// scripts/core/auth_state_cache.ts が実体。既存の import 経路を保つため再公開する。
// The auth state cache is shared with non-home pages (memo, ...), so
// scripts/core/auth_state_cache.ts owns it. Re-exported to keep import paths.
export {
  isCachedAuthStateFresh,
  readCachedAuthState,
  writeCachedAuthState,
} from "../../scripts/core/auth_state_cache";

// consumeAuthSuccessHint がローカルで使うため、再公開とは別に import する。
// Imported separately from the re-export above because consumeAuthSuccessHint uses it locally.
import { writeCachedAuthState } from "../../scripts/core/auth_state_cache";

// Google OAuth のコールバックが付けた認証成功のヒントを URL から取り除き、前の利用者の永続状態を破棄する。ヒントがなければ false。
// Strips the auth-success hint added by the Google OAuth callback from the URL and wipes the previous user's persisted state; returns false when the hint is absent.
export function consumeAuthSuccessHint() {
  if (typeof window === "undefined") return false;

  const url = new URL(window.location.href);
  if (url.searchParams.get(AUTH_SUCCESS_HINT.queryParam) !== AUTH_SUCCESS_HINT.successValue) {
    return false;
  }

  // このヒントは Google OAuth のコールバックが「/」へ直接（/login を経由せず）
  // 着地するときに付く。着地した時点で新規の認証が確定しているので、この端末に
  // 残っていた前の利用者の永続状態を今すぐ破棄する。ここで消しておけば、直後の
  // restoreHomeViewFromStorage が古い持ち主のレイアウトを一瞬でも復元しない。
  // ログイン中のまま別アカウントを追加した場合はログアウトを経由しないので、
  // 永続 SWR キャッシュとアイコンの表示キャッシュもここで消す。
  // This hint is attached when the Google OAuth callback lands directly on "/"
  // (bypassing /login). By the time it lands, a fresh authentication has just
  // been confirmed, so wipe whatever persisted state a previous user left on
  // this device right now. Clearing it here means the restoreHomeViewFromStorage
  // that follows never restores the previous owner's layout, even briefly.
  // Adding another account while signed in skips logout, so the persisted SWR
  // cache and the icon's display cache are cleared here as well.
  clearAllHomePagePersistedState();
  clearStoredUserScope();
  clearPersistentCache();
  clearCachedUserIconProfile();

  writeCachedAuthState(true);
  url.searchParams.delete(AUTH_SUCCESS_HINT.queryParam);
  const nextUrl = `${url.pathname}${url.search}${url.hash}`;
  window.history.replaceState({}, document.title, nextUrl || "/");
  return true;
}
