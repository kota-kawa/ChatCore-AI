import { formatDateTime } from "../../../lib/datetime";
import { asRecord } from "../../../lib/utils";

import type { PasskeyRecord, ProfileFormState } from "./page_types";

export { escapeHtml } from "../../core/html";

export function truncateTitle(title: string) {
  const chars = Array.from(title);
  return chars.length > 17 ? chars.slice(0, 17).join("") + "..." : title;
}

// 生の日付文字列を人間が読みやすい形式に変換する — 空値は空文字を返す
// Converts a raw date string to a human-readable format; returns empty string for falsy input
export function toDisplayDate(rawDate?: string): string {
  return formatDateTime(rawDate) || rawDate || "";
}

// 複数の空白文字を 1 つに正規化しトリムする — カード上のプレビューテキスト整形用
// Collapses consecutive whitespace and trims — used to format preview text on cards
export function normalizePreviewText(value?: string): string {
  return (value || "").replace(/\s+/g, " ").trim();
}

// API レスポンスの未知の配列を型安全な PasskeyRecord 配列に変換する
// Converts an unknown array from the API response into a type-safe PasskeyRecord array
export function normalizePasskeyRecords(rawPasskeys: unknown[]): PasskeyRecord[] {
  return rawPasskeys
    .map((rawPasskey) => {
      const passkey = asRecord(rawPasskey);
      const id = Number(passkey.id);
      // 数値として有効でない ID はスキップして配列から除外する
      // Skip entries whose id is not a finite number to avoid corrupted records
      if (!Number.isFinite(id)) {
        return null;
      }
      const label = typeof passkey.label === "string" && passkey.label.trim()
        ? passkey.label.trim()
        : "保存済みPasskey";
      return {
        id,
        label,
        credentialDeviceType: typeof passkey.credential_device_type === "string"
          ? passkey.credential_device_type
          : "不明",
        credentialBackedUp: Boolean(passkey.credential_backed_up),
        createdAt: typeof passkey.created_at === "string" ? passkey.created_at : "",
        lastUsedAt: typeof passkey.last_used_at === "string" ? passkey.last_used_at : ""
      };
    })
    .filter((passkey): passkey is PasskeyRecord => passkey !== null);
}

// Passkey の日時を表示用にフォーマットする — 値がなければ「未使用」を返す
// Formats a passkey datetime for display; returns "未使用" when the value is absent
export function formatPasskeyDateTime(value: string): string {
  if (!value) {
    return "未使用";
  }
  return formatDateTime(value) || "未使用";
}

// プロフィール情報から LLM に渡すデフォルトコンテキスト文字列を組み立てる
// Builds the default LLM context string from profile fields when no custom value has been saved
export function buildDefaultLlmProfileContext(profile: Pick<ProfileFormState, "username" | "email" | "bio">): string {
  const lines: string[] = [];
  const username = profile.username.trim();
  const email = profile.email.trim();
  const bio = profile.bio.trim();

  // 空フィールドは出力に含めず、入力済みの項目だけを改行区切りで連結する
  // Only include fields that have content so the context stays clean
  if (username) {
    lines.push(`名前: ${username}`);
  }
  if (email) {
    lines.push(`メールアドレス: ${email}`);
  }
  if (bio) {
    lines.push(`自己紹介: ${bio}`);
  }

  return lines.join("\n");
}
