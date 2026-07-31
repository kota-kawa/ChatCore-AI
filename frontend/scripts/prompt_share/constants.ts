import { STORAGE_KEYS } from "../core/constants";

export const AUTH_STATE_CACHE_KEY = STORAGE_KEYS.authStateCache;
export const PROMPTS_CACHE_KEY = "prompt_share.prompts.v1";
export const PROMPT_SHARE_TITLE = "Chat Core 共有プロンプト";
export const PROMPT_SHARE_TEXT = "このプロンプトを共有しました。";
export const TITLE_CHAR_LIMIT = 17;
export const CONTENT_CHAR_LIMIT = 160;
// アバター画像が未設定/読み込み失敗の場合に使うフォールバック画像
// Fallback image used when a user has no avatar or the image fails to load
export const DEFAULT_AUTHOR_AVATAR_URL = "/static/user-icon.png";
