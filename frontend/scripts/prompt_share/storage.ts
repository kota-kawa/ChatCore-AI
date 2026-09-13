import { AUTH_STATE_CACHE_KEY } from "./constants";

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
