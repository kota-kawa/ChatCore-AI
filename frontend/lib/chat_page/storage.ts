import { STORAGE_KEYS, AUTH_SUCCESS_HINT } from "../../scripts/core/constants";
import { normalizeChatMessageParts } from "./api_contract";
import { parseJsonText } from "../../scripts/core/runtime_validation";
import {
  clearAllCachedHistory,
  readCachedHistory,
  removeCachedHistory,
  writeCachedHistory,
  type HistoryCacheWriteResult,
} from "./history_cache";
import type { ChatRoomMode, ChatSender, StoredGenerationState, StoredHistoryEntry } from "./types";

const GENERATION_STATE_TTL_MS = 30 * 60 * 1000;
const GENERATION_STATE_KEY_PREFIX = "chatGeneration_";

// ログアウトを経由しないユーザー切り替え（別アカウントでの再ログインなど）から、
// 直前の利用者の永続状態を守るための「持ち主」マーカー。
// Marks who this browser's persisted chat state currently belongs to, so a user
// switch that skips logout does not leak the previous user's persisted state.
const USER_SCOPE_KEY = "chatcore.chat.userScope";
const ANONYMOUS_USER_SCOPE = "anonymous";

export type StoredHomePageViewState = "setup" | "chat";
type WritableHomePageViewState = StoredHomePageViewState | "launching";

export type StoredActiveChatRoom = {
  roomId: string;
  roomMode: ChatRoomMode;
};

function getStoredGenerationKey(roomId: string) {
  return `${GENERATION_STATE_KEY_PREFIX}${roomId}`;
}

function normalizeStoredRoomMode(rawMode: unknown): ChatRoomMode {
  return rawMode === "temporary" ? "temporary" : "normal";
}

function normalizeStoredHomePageViewState(rawState: unknown): StoredHomePageViewState {
  return rawState === "chat" ? "chat" : "setup";
}

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
      // 生成UIなどのパーツは保存時に書き込まれている。読み戻しで捨てると、リロード後に
      // Artifact が本文だけの吹き出しへ退化する。サーバーと同じ正規化を通して復元する。
      // Parts such as a generated UI are already written on save. Dropping them on read made
      // a reloaded artifact collapse into a text-only bubble, so they are restored through the
      // same normalization the server payloads use.
      const parts = normalizeChatMessageParts((entry as { parts?: unknown }).parts);
      normalized.push({ text, sender, ...(parts?.length ? { parts } : {}) });
    });

    return normalized;
  } catch {
    return [];
  }
}

export function writeStoredHistory(
  roomId: string,
  entries: StoredHistoryEntry[],
  roomMode: ChatRoomMode = "normal",
): StoredHistoryWriteResult {
  if (roomMode === "temporary") return skippedTemporaryWrite(roomId, entries.length);
  return writeCachedHistory(roomId, entries);
}

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

export function prependStoredHistory(
  roomId: string,
  entries: StoredHistoryEntry[],
  roomMode: ChatRoomMode = "normal",
): StoredHistoryWriteResult {
  if (roomMode === "temporary") return skippedTemporaryWrite(roomId, entries.length);
  const existing = readStoredHistory(roomId);
  return writeStoredHistory(roomId, [...entries, ...existing]);
}

export function removeStoredHistory(roomId: string) {
  removeCachedHistory(roomId);
  clearStoredGenerationState(roomId);
}

function normalizeStoredGenerationState(raw: unknown): StoredGenerationState | null {
  if (!raw || typeof raw !== "object") return null;
  const record = raw as {
    roomId?: unknown;
    roomMode?: unknown;
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
    lastEventId,
    streamedText,
    updatedAt,
  };
}

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

export function updateStoredGenerationState(
  roomId: string,
  updates: Partial<Pick<StoredGenerationState, "lastEventId" | "streamedText">>,
): boolean {
  const existing = readStoredGenerationState(roomId);
  if (!existing) return false;

  return writeStoredGenerationState({
    ...existing,
    ...updates,
  });
}

export function clearStoredGenerationState(roomId: string) {
  try {
    localStorage.removeItem(getStoredGenerationKey(roomId));
    const active = normalizeStoredGenerationState(
      parseJsonText(localStorage.getItem(STORAGE_KEYS.activeChatGeneration) || "null"),
    );
    if (!active || active.roomId === roomId) {
      localStorage.removeItem(STORAGE_KEYS.activeChatGeneration);
    }
  } catch {
    // ignore localStorage failures
  }
}

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
    // ignore localStorage failures
  }

  try {
    localStorage.removeItem(STORAGE_KEYS.activeChatRoomId);
    localStorage.removeItem(STORAGE_KEYS.activeChatRoomMode);
    localStorage.removeItem(STORAGE_KEYS.currentChatRoomId);
    localStorage.removeItem(STORAGE_KEYS.activeChatGeneration);
    localStorage.removeItem(STORAGE_KEYS.homePageViewState);
    localStorage.removeItem(STORAGE_KEYS.setupInfoDraft);
  } catch {
    // ignore localStorage failures
  }
}

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
      // ignore localStorage failures
    }
    return { changed: true };
  }

  if (previousScope === null) {
    try {
      localStorage.setItem(USER_SCOPE_KEY, nextScope);
    } catch {
      // ignore localStorage failures
    }
  }

  return { changed: false };
}

export function normalizeHistorySender(sender: string | undefined): ChatSender {
  if (sender === "user") return "user";
  if (sender === "thinking") return "thinking";
  return "assistant";
}

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

export function consumeAuthSuccessHint() {
  if (typeof window === "undefined") return false;

  const url = new URL(window.location.href);
  if (url.searchParams.get(AUTH_SUCCESS_HINT.queryParam) !== AUTH_SUCCESS_HINT.successValue) {
    return false;
  }

  writeCachedAuthState(true);
  url.searchParams.delete(AUTH_SUCCESS_HINT.queryParam);
  const nextUrl = `${url.pathname}${url.search}${url.hash}`;
  window.history.replaceState({}, document.title, nextUrl || "/");
  return true;
}
