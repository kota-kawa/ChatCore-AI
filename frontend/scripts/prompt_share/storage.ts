import type { PromptData } from "./types";
import { AUTH_STATE_CACHE_KEY, PROMPTS_CACHE_KEY } from "./constants";

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
