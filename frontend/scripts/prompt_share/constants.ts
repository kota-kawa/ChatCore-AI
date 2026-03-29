import { STORAGE_KEYS } from "../core/constants";

export const AUTH_STATE_CACHE_KEY = STORAGE_KEYS.authStateCache;
export const PROMPTS_CACHE_KEY = "prompt_share.prompts.v1";
export const PROMPT_IMAGE_MAX_BYTES = 5 * 1024 * 1024;
export const ACCEPTED_PROMPT_IMAGE_TYPES = new Set([
  "image/png",
  "image/jpeg",
  "image/webp",
  "image/gif"
]);
export const ACCEPTED_PROMPT_IMAGE_EXTENSIONS = [".png", ".jpg", ".jpeg", ".webp", ".gif"];
export const PROMPT_SHARE_TITLE = "Chat Core 共有プロンプト";
export const PROMPT_SHARE_TEXT = "このプロンプトを共有しました。";
export const TITLE_CHAR_LIMIT = 17;
export const CONTENT_CHAR_LIMIT = 160;
