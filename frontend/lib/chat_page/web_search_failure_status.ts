// Web 検索の失敗イベントでサーバーが返すエラーコードを、画面が扱う失敗の種類へ対応づける。
// Maps the error code the server sends with a web-search failure event to the failure status the UI handles.
// Used by lib/chat_page/generation_stream_events.ts.

/**
 * Web 検索の失敗を知らせる SSE イベントでサーバーが使う、変わらないエラーコード。
 *
 * 失敗の種類をローカライズ済みのエラーメッセージから推測してはならない。
 * メッセージの文言は表示用のデータで、ロケールや言い回しによって変わるため。
 *
 * Stable server error codes used by the web-search SSE failure event.
 *
 * The UI must not infer the failure category from a localized error message:
 * message text is presentation data and can change with locale or wording.
 */
export type WebSearchFailureCode =
  | "web_search.configuration"
  | "web_search.quota_exceeded"
  | "web_search.request_failed";

// 画面が扱う失敗の種類。設定の不備・上限超過・リクエスト失敗の 3 つ。
// Failure kinds the UI handles: misconfiguration, quota exceeded, or request failure.
export type WebSearchFailureStatus = "configuration" | "quota_exceeded" | "request_failed";

// 未知のコードや文字列以外は request_failed に倒して扱う。
// Unknown codes and non-string values are treated as request_failed.
export function getWebSearchFailureStatus(code: unknown): WebSearchFailureStatus {
  switch (code) {
    case "web_search.configuration":
      return "configuration";
    case "web_search.quota_exceeded":
      return "quota_exceeded";
    case "web_search.request_failed":
    default:
      return "request_failed";
  }
}
