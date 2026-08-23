/**
 * Stable server error codes used by the web-search SSE failure event.
 *
 * The UI must not infer the failure category from a localized error message:
 * message text is presentation data and can change with locale or wording.
 */
export type WebSearchFailureCode =
  | "web_search.configuration"
  | "web_search.quota_exceeded"
  | "web_search.request_failed";

export type WebSearchFailureStatus = "configuration" | "quota_exceeded" | "request_failed";

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
