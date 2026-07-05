import { CACHE_TTL_MS, STORAGE_KEYS, AUTH_SUCCESS_HINT } from "../../scripts/core/constants";
import { parseJsonText } from "../../scripts/core/runtime_validation";
import type { ChatRoomMode, ChatSender, StoredGenerationState, StoredHistoryEntry } from "./types";

const GENERATION_STATE_TTL_MS = 30 * 60 * 1000;

export type StoredHomePageViewState = "setup" | "chat";
type WritableHomePageViewState = StoredHomePageViewState | "launching";

export type StoredActiveChatRoom = {
  roomId: string;
  roomMode: ChatRoomMode;
};

function getStoredHistoryKey(roomId: string) {
  return `chatHistory_${roomId}`;
}

function getStoredGenerationKey(roomId: string) {
  return `chatGeneration_${roomId}`;
}

function isQuotaExceededError(error: unknown) {
  if (!error || typeof error !== "object") return false;

  const { name, code } = error as { name?: unknown; code?: unknown };
  return name === "QuotaExceededError" || code === 22 || code === 1014;
}

function persistStoredHistory(key: string, entries: StoredHistoryEntry[]) {
  localStorage.setItem(key, JSON.stringify(entries));
}

function normalizeStoredRoomMode(rawMode: unknown): ChatRoomMode {
  return rawMode === "temporary" ? "temporary" : "normal";
}

function normalizeStoredHomePageViewState(rawState: unknown): StoredHomePageViewState {
  return rawState === "chat" ? "chat" : "setup";
}

export function readStoredHomePageViewState(): StoredHomePageViewState {
  try {
    return normalizeStoredHomePageViewState(localStorage.getItem(STORAGE_KEYS.homePageViewState));
  } catch {
    return "setup";
  }
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

export type StoredHistoryWriteResult = {
  stored: boolean;
  truncated: boolean;
  retainedEntries: number;
  droppedEntries: number;
  reason?: "quota_exceeded" | "storage_error";
};

function storedHistoryWriteSuccess(entries: StoredHistoryEntry[]): StoredHistoryWriteResult {
  return {
    stored: true,
    truncated: false,
    retainedEntries: entries.length,
    droppedEntries: 0,
  };
}

function storedHistoryWriteFailure(
  entries: StoredHistoryEntry[],
  reason: StoredHistoryWriteResult["reason"],
): StoredHistoryWriteResult {
  return {
    stored: false,
    truncated: false,
    retainedEntries: 0,
    droppedEntries: entries.length,
    reason,
  };
}

export function readStoredHistory(roomId: string): StoredHistoryEntry[] {
  try {
    const raw = localStorage.getItem(getStoredHistoryKey(roomId));
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
      normalized.push({ text, sender });
    });

    return normalized;
  } catch {
    return [];
  }
}

export function writeStoredHistory(roomId: string, entries: StoredHistoryEntry[]): StoredHistoryWriteResult {
  const storageKey = getStoredHistoryKey(roomId);
  try {
    persistStoredHistory(storageKey, entries);
    return storedHistoryWriteSuccess(entries);
  } catch (error) {
    if (!isQuotaExceededError(error) || entries.length <= 1) {
      return storedHistoryWriteFailure(entries, isQuotaExceededError(error) ? "quota_exceeded" : "storage_error");
    }

    // Preserve the newest messages when storage is near quota.
    let retainedEntries = entries;
    while (retainedEntries.length > 1) {
      const nextLength = Math.max(1, Math.floor(retainedEntries.length * 0.75));
      retainedEntries =
        nextLength === retainedEntries.length
          ? retainedEntries.slice(1)
          : retainedEntries.slice(retainedEntries.length - nextLength);

      try {
        persistStoredHistory(storageKey, retainedEntries);
        return {
          stored: true,
          truncated: true,
          retainedEntries: retainedEntries.length,
          droppedEntries: entries.length - retainedEntries.length,
          reason: "quota_exceeded",
        };
      } catch (retryError) {
        if (!isQuotaExceededError(retryError)) {
          return storedHistoryWriteFailure(entries, "storage_error");
        }
      }
    }
  }

  return storedHistoryWriteFailure(entries, "quota_exceeded");
}

export function appendStoredHistory(roomId: string, entry: StoredHistoryEntry): StoredHistoryWriteResult {
  const existing = readStoredHistory(roomId);
  return writeStoredHistory(roomId, [...existing, entry]);
}

export function prependStoredHistory(roomId: string, entries: StoredHistoryEntry[]): StoredHistoryWriteResult {
  const existing = readStoredHistory(roomId);
  return writeStoredHistory(roomId, [...entries, ...existing]);
}

export function removeStoredHistory(roomId: string) {
  try {
    localStorage.removeItem(getStoredHistoryKey(roomId));
  } catch {
    // ignore localStorage failures
  }
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

export function readCachedAuthState() {
  try {
    const cached = localStorage.getItem(STORAGE_KEYS.authStateCache);
    if (cached === "1") return true;
    if (cached === "0") return false;
  } catch {
    // ignore localStorage failures
  }
  return null;
}

export function isCachedAuthStateFresh() {
  try {
    const cachedAtRaw = localStorage.getItem(STORAGE_KEYS.authStateCachedAt);
    if (!cachedAtRaw) return false;
    const cachedAt = Number(cachedAtRaw);
    if (!Number.isFinite(cachedAt)) return false;
    return Date.now() - cachedAt <= CACHE_TTL_MS.authState;
  } catch {
    return false;
  }
}

export function writeCachedAuthState(loggedIn: boolean) {
  try {
    localStorage.setItem(STORAGE_KEYS.authStateCache, loggedIn ? "1" : "0");
    localStorage.setItem(STORAGE_KEYS.authStateCachedAt, String(Date.now()));
  } catch {
    // ignore localStorage failures
  }
}

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
