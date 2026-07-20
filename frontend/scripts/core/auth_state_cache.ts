import { CACHE_TTL_MS, STORAGE_KEYS } from "./constants";

// ページ間で共有する認証状態キャッシュ。トップページ・メモなど、認証依存のUIを
// 持つ画面が「直前のログイン状態」を最初のペイント前に復元するために使う。
// サーバーが返す静的HTMLは常に未ログイン状態なので、これが無いとログイン済み
// ユーザーにも一瞬ゲスト向けUIが描画される。
// Auth state cache shared across pages. Screens with auth-dependent UI (home,
// memo, ...) use it to restore the last known login state before the first
// paint. The statically served HTML is always the logged-out view, so without
// this a signed-in user briefly sees the guest UI.

// _document.tsx のブートスクリプトがハイドレーション前に立てる属性。
// CSS がゲスト専用要素を隠すために参照する。
// Attribute set by the bootstrap script in _document.tsx before hydration.
// CSS keys off it to hide guest-only elements.
export const AUTH_BOOT_ATTRIBUTE = "data-cc-auth";

export function readCachedAuthState(): boolean | null {
  try {
    const cached = localStorage.getItem(STORAGE_KEYS.authStateCache);
    if (cached === "1") return true;
    if (cached === "0") return false;
  } catch {
    // ignore localStorage failures
  }
  return null;
}

export function isCachedAuthStateFresh(): boolean {
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

// キャッシュを反映し終えたらフラグを外し、以降の表示はReactに委ねる。
// サーバー確認の結果がキャッシュと異なる場合にCSSが古い状態を固定しないよう、
// 必ずキャッシュ適用と同じコミットで呼ぶこと。
// Release the flag once the cached state has been applied so React owns the
// display from then on. Always call it in the same commit that applies the
// cache, so stale CSS cannot pin the old state when the server disagrees.
export function releaseAuthBootAttribute() {
  if (typeof document === "undefined") return;
  document.documentElement.removeAttribute(AUTH_BOOT_ATTRIBUTE);
}
