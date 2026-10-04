// 右上ユーザーアイコンの表示キャッシュ。認証確認より前にアバターを出すためのもので、
// 利用者が替わるときは必ず消す。
// Display cache for the top-right user icon, used to paint the avatar before the auth
// check returns. It must be cleared whenever the user changes.

export const DEFAULT_AVATAR_URL = "/static/user-icon.png";
const AVATAR_CACHE_KEY = "chatcore.userIcon.avatarUrl";
const USERNAME_CACHE_KEY = "chatcore.userIcon.username";

function normalizeText(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}

export function readCachedUserIconProfile() {
  try {
    const avatarUrl = normalizeText(localStorage.getItem(AVATAR_CACHE_KEY));
    if (!avatarUrl) {
      return null;
    }

    return {
      avatarUrl,
      username: normalizeText(localStorage.getItem(USERNAME_CACHE_KEY))
    };
  } catch {
    return null;
  }
}

export function writeCachedUserIconProfile(avatarUrl: string, username: string) {
  const url = avatarUrl || DEFAULT_AVATAR_URL;
  try {
    localStorage.setItem(AVATAR_CACHE_KEY, url);
    if (username) {
      localStorage.setItem(USERNAME_CACHE_KEY, username);
    } else {
      localStorage.removeItem(USERNAME_CACHE_KEY);
    }
  } catch {
    // localStorage が使えなくても表示は継続する
  }
}

export function clearCachedUserIconProfile() {
  try {
    localStorage.removeItem(AVATAR_CACHE_KEY);
    localStorage.removeItem(USERNAME_CACHE_KEY);
  } catch {
    // localStorage が使えなくても表示は継続する
  }
}
