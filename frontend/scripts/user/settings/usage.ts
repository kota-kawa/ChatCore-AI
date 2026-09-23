import type { Locale } from "../../../lib/i18n/config";

// 上限の区切りは日本時間で決まるため、表示も日本時間に固定する。
// Limits reset on Japan-time boundaries, so reset times are always shown in Japan time.
const USAGE_TIME_ZONE = "Asia/Tokyo";

// 使用率（0〜1）を、バーの幅と読み上げに使う 0〜100 の整数へ丸める。
// 上限に届いていないのに 100% と表示しないよう、1 未満は 99 で止める。
// Round a 0–1 share into the 0–100 integer used for the bar and its label. Anything below
// the limit stops at 99 so the page never shows 100% before the limit is actually reached.
export function usagePercent(usedRatio: number): number {
  if (!Number.isFinite(usedRatio) || usedRatio <= 0) return 0;
  if (usedRatio >= 1) return 100;
  return Math.min(Math.round(usedRatio * 100), 99);
}

// リセット時刻を「9月24日(木) 0:00」／「Thu, Sep 24, 12:00 AM」の形で返す。
// Format a reset time such as "9月24日(木) 0:00" or "Thu, Sep 24, 12:00 AM".
export function formatUsageResetTime(isoTime: string, locale: Locale): string {
  const date = new Date(isoTime);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(locale === "ja" ? "ja-JP" : "en-US", {
    timeZone: USAGE_TIME_ZONE,
    month: "short",
    day: "numeric",
    weekday: "short",
    hour: "numeric",
    minute: "2-digit"
  }).format(date);
}
