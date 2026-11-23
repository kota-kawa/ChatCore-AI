// SSR のリクエストヘッダーから、公開 URL の組み立てに使うオリジン（scheme://host）を求める。
// Derives the origin (scheme://host) used to build public URLs from the headers of an SSR request.
import type { IncomingMessage } from "http";

// Hostヘッダーの値を正規化する（配列の場合は先頭を取得）
// Normalize the Host header value (take the first if it's an array)
function normalizeHostHeader(header: string | string[] | undefined) {
  if (Array.isArray(header)) return header[0] || "";
  return header || "";
}

// X-Forwarded-Protoヘッダーを正規化する（カンマ区切りの最初の値を取得）
// Normalize the X-Forwarded-Proto header (take the first comma-separated value)
function normalizeProtoHeader(header: string | string[] | undefined) {
  const raw = Array.isArray(header) ? header[0] : header;
  if (!raw) return "";
  return raw.split(",")[0]?.trim() || "";
}

// リバースプロキシ経由でもリクエストされたオリジンを返す。ホストが分からないときは空文字を返す。
// Returns the requested origin even behind a reverse proxy; an empty string when the host is unknown.
export function getRequestOrigin(req: Pick<IncomingMessage, "headers">) {
  const host = normalizeHostHeader(req.headers["x-forwarded-host"]) || normalizeHostHeader(req.headers.host);
  const proto = normalizeProtoHeader(req.headers["x-forwarded-proto"])
    || (process.env.NODE_ENV === "development" ? "http" : "https");
  return host ? `${proto}://${host}` : "";
}
