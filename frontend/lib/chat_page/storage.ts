import { CACHE_TTL_MS, STORAGE_KEYS, AUTH_SUCCESS_HINT } from "../../scripts/core/constants";
import { parseJsonText } from "../../scripts/core/runtime_validation";
import type { ChatSender, StoredHistoryEntry } from "./types";

function getStoredHistoryKey(roomId: string) {
  return `chatHistory_${roomId}`;
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

export function writeStoredHistory(roomId: string, entries: StoredHistoryEntry[]) {
  try {
    localStorage.setItem(getStoredHistoryKey(roomId), JSON.stringify(entries));
  } catch {
    // ignore localStorage failures
  }
}

export function appendStoredHistory(roomId: string, entry: StoredHistoryEntry) {
  const existing = readStoredHistory(roomId);
  writeStoredHistory(roomId, [...existing, entry]);
}

export function prependStoredHistory(roomId: string, entries: StoredHistoryEntry[]) {
  const existing = readStoredHistory(roomId);
  writeStoredHistory(roomId, [...entries, ...existing]);
}

export function removeStoredHistory(roomId: string) {
  try {
    localStorage.removeItem(getStoredHistoryKey(roomId));
  } catch {
    // ignore localStorage failures
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
