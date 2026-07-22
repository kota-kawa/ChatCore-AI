// 遅い・不安定な回線で「再訪時に前回データを即表示してから裏で更新する」ための
// localStorage バックの SWR キャッシュプロバイダー。
// A localStorage-backed SWR cache provider that lets revisits render the previous
// data instantly and revalidate in the background — the core of slow-network UX.
//
// 安全性のための制約 / Safety constraints:
//   - allowlist プレフィックスに一致するキーのみ永続化する（機微データは対象外）。
//     Persist only keys matching an allowlist prefix (sensitive data stays in memory).
//   - data フィールドのみ保存し、error / isValidating は保存しない。
//     Persist only the `data` field; never persist transient error/validating state.
//   - TTL を超えたエントリは読み込み時に破棄する。
//     Drop entries that exceed the TTL on load.
//   - エントリ数の上限を設け、超過時は古いものから捨てる。
//     Cap the number of entries; evict the oldest beyond the cap.
//   - SSR では何もしない（typeof window ガード）。
//     No-op during SSR (guarded by typeof window).

import type { Cache, State } from "swr";

const STORAGE_KEY = "chatcore.swr.cache.v1";
// 既定の TTL（ミリ秒）。これを超えたら即表示はせず、通常どおり再取得する。
// Default TTL (ms). Beyond this, the stale entry is dropped instead of shown.
const DEFAULT_TTL_MS = 1000 * 60 * 30; // 30 minutes
const MAX_ENTRIES = 80;
// localStorage 書き込みのデバウンス（ミリ秒）。連続する set をまとめる。
// Debounce window (ms) for localStorage writes; coalesces bursts of `set` calls.
const PERSIST_DEBOUNCE_MS = 400;

// 永続化を許可するキーのプレフィックス一覧（安全な読み取りのみ）。
// Allowlist of key prefixes that may be persisted (safe reads only).
const PERSIST_ALLOWLIST = [
  "/memo/api/",
  "/prompt_share/api/",
  "/api/settings",
  "/api/profile",
  "/api/current_user",
] as const;

type PersistedEntry = { data: unknown; ts: number };
type PersistedShape = Record<string, PersistedEntry>;

function canPersistKey(key: string): boolean {
  return PERSIST_ALLOWLIST.some((prefix) => key.startsWith(prefix));
}

function readStorage(): PersistedShape {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== "object") return {};
    return parsed as PersistedShape;
  } catch {
    return {};
  }
}

function writeStorage(shape: PersistedShape): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(shape));
  } catch {
    // QuotaExceeded などは無視する（永続化はあくまで最適化）。
    // Ignore quota/serialization errors — persistence is best-effort optimization only.
  }
}

// 期限切れエントリを除外し、上限を超えた古いエントリを捨てる。
// Drop expired entries and evict the oldest ones beyond the cap.
function pruneShape(shape: PersistedShape, ttlMs: number): PersistedShape {
  const now = Date.now();
  const fresh = Object.entries(shape).filter(([, entry]) => entry && now - entry.ts < ttlMs);
  fresh.sort((a, b) => b[1].ts - a[1].ts);
  return Object.fromEntries(fresh.slice(0, MAX_ENTRIES));
}

/**
 * SWR の provider に渡すキャッシュ実装を生成する。
 * Build the cache implementation passed to SWR's `provider`.
 *
 * @param defaultCache SWR が渡す既定キャッシュ（Map 互換、初期データ入り）。
 *                     The default cache SWR passes in (Map-compatible, pre-populated).
 */
export function createPersistentCacheProvider(ttlMs: number = DEFAULT_TTL_MS) {
  return (defaultCache: Readonly<Cache>): Cache => {
    const map = defaultCache as unknown as Map<string, State>;

    let flushTimer: ReturnType<typeof setTimeout> | null = null;
    const dirty = new Set<string>();

    const scheduleFlush = () => {
      if (typeof window === "undefined" || flushTimer !== null) return;
      flushTimer = setTimeout(() => {
        flushTimer = null;
        const shape = readStorage();
        for (const key of dirty) {
          const state = map.get(key);
          if (state && state.data !== undefined && state.error === undefined) {
            shape[key] = { data: state.data, ts: Date.now() };
          } else {
            delete shape[key];
          }
        }
        dirty.clear();
        writeStorage(pruneShape(shape, ttlMs));
      }, PERSIST_DEBOUNCE_MS);
    };

    return {
      keys: () => map.keys(),
      get: (key: string) => map.get(key),
      set: (key: string, value: State) => {
        map.set(key, value);
        if (canPersistKey(key)) {
          dirty.add(key);
          scheduleFlush();
        }
      },
      delete: (key: string) => {
        map.delete(key);
        if (canPersistKey(key)) {
          dirty.add(key);
          scheduleFlush();
        }
      },
    };
  };
}

/**
 * localStorage のキャッシュを、React のハイドレーション完了後に適用するための
 * 安全なエントリ一覧を返す。
 *
 * Reading browser storage while SWR creates its cache would make the first
 * client render differ from the server-rendered HTML. The caller must invoke
 * this from a client-side effect and publish each entry through SWR's mutate.
 */
export function loadPersistentCacheEntries(ttlMs: number = DEFAULT_TTL_MS): Array<[string, unknown]> {
  const persisted = pruneShape(readStorage(), ttlMs);
  writeStorage(persisted);
  return Object.entries(persisted)
    .filter(([key]) => canPersistKey(key))
    .map(([key, entry]) => [key, entry.data]);
}

/**
 * ログアウト/ユーザー切替時に永続キャッシュを完全に消去する。
 * Clear the persisted cache entirely on logout / user switch.
 */
export function clearPersistentCache(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
}

export const __test__ = { canPersistKey, pruneShape, STORAGE_KEY, DEFAULT_TTL_MS };
