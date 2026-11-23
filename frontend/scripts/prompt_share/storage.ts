// 公開投稿画面で使うブラウザー保存データを読み書きする。
// Reads and writes browser storage used by public post views.

import { AUTH_STATE_CACHE_KEY } from "./constants";

export function writeCachedAuthState(loggedIn: boolean) {
  try {
    localStorage.setItem(AUTH_STATE_CACHE_KEY, loggedIn ? "1" : "0");
  } catch {
    // localStorage が使えない環境では保存をスキップ
  }
}
