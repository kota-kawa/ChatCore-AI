import type { StoredHistoryEntry } from "./types";

const HISTORY_KEY_PREFIX = "chatHistory_";
const HISTORY_INDEX_KEY = "chatcore.chat.historyIndex.v1";
const HISTORY_CACHE_TTL_MS = 7 * 24 * 60 * 60 * 1000;
const MAX_CACHED_HISTORY_ROOMS = 6;
const MAX_HISTORY_CACHE_BYTES = 2 * 1024 * 1024;
const MAX_HISTORY_ROOM_BYTES = 512 * 1024;

type HistoryIndex = Record<string, number>;

export type HistoryCacheWriteResult = {
  stored: boolean;
  truncated: boolean;
  retainedEntries: number;
  droppedEntries: number;
  reason?: "cache_limit" | "quota_exceeded" | "storage_error";
};

type CachedRoom = {
  roomId: string;
  key: string;
  bytes: number;
  lastAccessedAt: number;
};

function getHistoryKey(roomId: string) {
  return `${HISTORY_KEY_PREFIX}${roomId}`;
}

function approximateStorageBytes(value: string) {
  // localStorage stores DOMStrings. Counting two bytes per UTF-16 code unit is
  // intentionally conservative across browser quota implementations.
  return value.length * 2;
}

function isQuotaExceededError(error: unknown) {
  if (!error || typeof error !== "object") return false;

  const { name, code } = error as { name?: unknown; code?: unknown };
  return name === "QuotaExceededError" || code === 22 || code === 1014;
}

function readHistoryIndex(): HistoryIndex {
  try {
    const raw = localStorage.getItem(HISTORY_INDEX_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};

    const index: HistoryIndex = {};
    Object.entries(parsed).forEach(([roomId, timestamp]) => {
      if (typeof timestamp === "number" && Number.isFinite(timestamp) && timestamp > 0) {
        index[roomId] = timestamp;
      }
    });
    return index;
  } catch {
    return {};
  }
}

function writeHistoryIndex(index: HistoryIndex) {
  try {
    if (Object.keys(index).length === 0) {
      localStorage.removeItem(HISTORY_INDEX_KEY);
      return;
    }
    localStorage.setItem(HISTORY_INDEX_KEY, JSON.stringify(index));
  } catch {
    // The cached messages remain usable without the best-effort LRU metadata.
  }
}

function collectCachedRooms(index: HistoryIndex): CachedRoom[] {
  const rooms: CachedRoom[] = [];
  try {
    for (let indexPosition = 0; indexPosition < localStorage.length; indexPosition += 1) {
      const key = localStorage.key(indexPosition);
      if (!key?.startsWith(HISTORY_KEY_PREFIX)) continue;
      const roomId = key.slice(HISTORY_KEY_PREFIX.length);
      const value = localStorage.getItem(key);
      if (!roomId || value === null) continue;
      rooms.push({
        roomId,
        key,
        bytes: approximateStorageBytes(value),
        lastAccessedAt: index[roomId] ?? 0,
      });
    }
  } catch {
    return [];
  }
  return rooms;
}

function removeCachedRoom(room: Pick<CachedRoom, "roomId" | "key">, index: HistoryIndex) {
  try {
    localStorage.removeItem(room.key);
  } catch {
    // Best-effort cache cleanup must not interrupt the chat UI.
  }
  delete index[room.roomId];
}

function sortOldestFirst(rooms: CachedRoom[]) {
  return rooms.sort((left, right) => left.lastAccessedAt - right.lastAccessedAt);
}

function pruneOtherRooms(roomId: string, candidateBytes: number, index: HistoryIndex) {
  const now = Date.now();
  const allRooms = collectCachedRooms(index);

  allRooms.forEach((room) => {
    if (
      room.roomId !== roomId
      && room.lastAccessedAt > 0
      && now - room.lastAccessedAt > HISTORY_CACHE_TTL_MS
    ) {
      removeCachedRoom(room, index);
    }
  });

  const otherRooms = sortOldestFirst(
    collectCachedRooms(index).filter((room) => room.roomId !== roomId),
  );
  let otherBytes = otherRooms.reduce((total, room) => total + room.bytes, 0);
  let roomCountWithCandidate = otherRooms.length + 1;

  while (
    otherRooms.length > 0
    && (
      roomCountWithCandidate > MAX_CACHED_HISTORY_ROOMS
      || otherBytes + candidateBytes > MAX_HISTORY_CACHE_BYTES
    )
  ) {
    const oldest = otherRooms.shift();
    if (!oldest) break;
    removeCachedRoom(oldest, index);
    otherBytes -= oldest.bytes;
    roomCountWithCandidate -= 1;
  }
}

function serializeWithinRoomLimit(entries: StoredHistoryEntry[]) {
  let retainedEntries = entries;
  let serialized = JSON.stringify(retainedEntries);
  let contentReduced = false;

  while (
    approximateStorageBytes(serialized) > MAX_HISTORY_ROOM_BYTES
    && retainedEntries.length > 1
  ) {
    const nextLength = Math.max(1, Math.floor(retainedEntries.length * 0.75));
    retainedEntries = retainedEntries.slice(retainedEntries.length - nextLength);
    serialized = JSON.stringify(retainedEntries);
  }

  if (approximateStorageBytes(serialized) > MAX_HISTORY_ROOM_BYTES) {
    retainedEntries = retainedEntries.map(({ text, sender }) => ({ text, sender }));
    serialized = JSON.stringify(retainedEntries);
    contentReduced = true;
  }

  if (approximateStorageBytes(serialized) > MAX_HISTORY_ROOM_BYTES) {
    retainedEntries = [];
    serialized = "[]";
    contentReduced = true;
  }

  return { contentReduced, retainedEntries, serialized };
}

function successResult(
  originalEntries: StoredHistoryEntry[],
  retainedEntries: StoredHistoryEntry[],
  reason?: HistoryCacheWriteResult["reason"],
  contentReduced = false,
): HistoryCacheWriteResult {
  return {
    stored: true,
    truncated: contentReduced || retainedEntries.length !== originalEntries.length,
    retainedEntries: retainedEntries.length,
    droppedEntries: originalEntries.length - retainedEntries.length,
    ...(reason ? { reason } : {}),
  };
}

function failureResult(
  entries: StoredHistoryEntry[],
  reason: HistoryCacheWriteResult["reason"],
): HistoryCacheWriteResult {
  return {
    stored: false,
    truncated: false,
    retainedEntries: 0,
    droppedEntries: entries.length,
    reason,
  };
}

export function readCachedHistory(roomId: string): string | null {
  try {
    const raw = localStorage.getItem(getHistoryKey(roomId));
    if (raw === null) return null;
    const index = readHistoryIndex();
    index[roomId] = Date.now();
    writeHistoryIndex(index);
    return raw;
  } catch {
    return null;
  }
}

export function writeCachedHistory(
  roomId: string,
  entries: StoredHistoryEntry[],
): HistoryCacheWriteResult {
  if (entries.length === 0) {
    removeCachedHistory(roomId);
    return successResult(entries, entries);
  }

  const originalEntries = entries;
  let { contentReduced, retainedEntries, serialized } = serializeWithinRoomLimit(entries);
  const index = readHistoryIndex();
  pruneOtherRooms(roomId, approximateStorageBytes(serialized), index);

  const storageKey = getHistoryKey(roomId);
  let quotaRecoveryUsed = false;

  while (true) {
    try {
      localStorage.setItem(storageKey, serialized);
      index[roomId] = Date.now();
      writeHistoryIndex(index);
      const reason = quotaRecoveryUsed
        ? "quota_exceeded"
        : contentReduced || retainedEntries.length !== originalEntries.length
          ? "cache_limit"
          : undefined;
      return successResult(originalEntries, retainedEntries, reason, contentReduced);
    } catch (error) {
      if (!isQuotaExceededError(error)) {
        return failureResult(originalEntries, "storage_error");
      }
      quotaRecoveryUsed = true;

      const oldestOtherRoom = sortOldestFirst(
        collectCachedRooms(index).filter((room) => room.roomId !== roomId),
      )[0];
      if (oldestOtherRoom) {
        removeCachedRoom(oldestOtherRoom, index);
        continue;
      }

      if (retainedEntries.length <= 1) {
        return failureResult(originalEntries, "quota_exceeded");
      }

      const nextLength = Math.max(1, Math.floor(retainedEntries.length * 0.75));
      retainedEntries = retainedEntries.slice(retainedEntries.length - nextLength);
      serialized = JSON.stringify(retainedEntries);
      contentReduced = contentReduced || retainedEntries.length !== originalEntries.length;
    }
  }
}

export function removeCachedHistory(roomId: string) {
  const index = readHistoryIndex();
  removeCachedRoom({ roomId, key: getHistoryKey(roomId) }, index);
  writeHistoryIndex(index);
}

export const __test__ = {
  HISTORY_CACHE_TTL_MS,
  HISTORY_INDEX_KEY,
  HISTORY_KEY_PREFIX,
  MAX_CACHED_HISTORY_ROOMS,
  MAX_HISTORY_CACHE_BYTES,
  MAX_HISTORY_ROOM_BYTES,
};
