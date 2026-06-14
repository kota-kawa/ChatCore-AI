/**
 * 値がRecord型（オブジェクト）かどうかを判定する
 * Check if the value is a Record (object)
 */
export function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object";
}

/**
 * 値をRecord型（オブジェクト）として取得する。不正な場合は空オブジェクトを返す
 * Get the value as a Record (object). Return an empty object if invalid
 */
export function asRecord(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {};
}

/**
 * 値を文字列として取得する。nullやundefinedの場合は空文字を返す
 * Get the value as a string. Return an empty string if null or undefined
 */
export function asString(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }
  if (value === null || value === undefined) {
    return "";
  }
  return String(value);
}

/**
 * 値をID（文字列）として取得する。文字列または数値以外は空文字を返す
 * Get the value as an ID (string). Return an empty string if not a string or number
 */
export function asId(value: unknown): string {
  if (typeof value === "string" || typeof value === "number") {
    return String(value);
  }
  return "";
}

/**
 * sessionStorageからJSONデータを読み込む
 * Read JSON data from sessionStorage
 */
export function readSessionJson<T>(key: string, fallback: T): T {
  // サーバーサイドレンダリング時のエラーを防ぐ
  // Prevent errors during server-side rendering
  if (typeof window === "undefined") return fallback;
  try {
    const raw = window.sessionStorage.getItem(key);
    if (raw === null) return fallback;
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

/**
 * sessionStorageへJSONデータを書き込む
 * Write JSON data to sessionStorage
 */
export function writeSessionJson(key: string, value: unknown): void {
  // サーバーサイドレンダリング時は何もしない
  // Do nothing during server-side rendering
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    // クォータ超過や無効化されている場合のエラーを無視する
    // ignore quota / disabled errors
  }
}
