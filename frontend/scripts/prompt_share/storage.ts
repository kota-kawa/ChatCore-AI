import type { PromptData } from "./types";
import { AUTH_STATE_CACHE_KEY, DETAIL_READING_SIZE_KEY, PROMPTS_CACHE_KEY } from "./constants";

// 詳細モーダルの本文サイズは3段階。CSS側は data-reading-size 属性で切り替える
// Reading size has three steps; the stylesheet switches on the data-reading-size attribute
export const READING_SIZES = ["compact", "default", "large"] as const;
export type ReadingSize = (typeof READING_SIZES)[number];
export const DEFAULT_READING_SIZE: ReadingSize = "default";

function isReadingSize(value: string | null): value is ReadingSize {
  return value !== null && (READING_SIZES as readonly string[]).includes(value);
}

export function readCachedAuthState() {
  try {
    const cached = localStorage.getItem(AUTH_STATE_CACHE_KEY);
    if (cached === "1") return true;
    if (cached === "0") return false;
  } catch {
    // localStorage が使えない環境ではキャッシュを無視
  }
  return null;
}

export function writeCachedAuthState(loggedIn: boolean) {
  try {
    localStorage.setItem(AUTH_STATE_CACHE_KEY, loggedIn ? "1" : "0");
  } catch {
    // localStorage が使えない環境では保存をスキップ
  }
}

export function readPromptCache() {
  try {
    const raw = sessionStorage.getItem(PROMPTS_CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return null;
    return parsed as PromptData[];
  } catch {
    return null;
  }
}

export function writePromptCache(prompts: PromptData[]) {
  try {
    sessionStorage.setItem(PROMPTS_CACHE_KEY, JSON.stringify(prompts));
  } catch {
    // sessionStorage が使えない環境では保存をスキップ
  }
}

export function readReadingSize(): ReadingSize {
  try {
    const stored = localStorage.getItem(DETAIL_READING_SIZE_KEY);
    if (isReadingSize(stored)) return stored;
  } catch {
    // localStorage が使えない環境では既定値を使う
  }
  return DEFAULT_READING_SIZE;
}

export function writeReadingSize(size: ReadingSize) {
  try {
    localStorage.setItem(DETAIL_READING_SIZE_KEY, size);
  } catch {
    // localStorage が使えない環境では保存をスキップ
  }
}
