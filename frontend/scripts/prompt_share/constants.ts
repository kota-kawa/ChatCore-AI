import { STORAGE_KEYS } from "../core/constants";

export const AUTH_STATE_CACHE_KEY = STORAGE_KEYS.authStateCache;
export const CONTENT_CHAR_LIMIT = 160;
// アバター画像が未設定/読み込み失敗の場合に使うフォールバック画像
// Fallback image used when a user has no avatar or the image fails to load
export const DEFAULT_AUTHOR_AVATAR_URL = "/static/user-icon.png";
