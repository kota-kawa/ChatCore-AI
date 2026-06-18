// SWR と既存の resilientFetch を繋ぐ共通フェッチャー。
// A shared SWR fetcher built on top of the existing resilientFetch helper.
//
// 目的 / Goals:
//   - すべての GET 読み取りに timeout + 指数バックオフ retry を一括付与する（遅い・不安定な回線対策）。
//     Apply timeout + exponential-backoff retry to every GET read (resilience on slow/flaky networks).
//   - HTTP エラーを一貫した形に正規化し、SWR の error として扱えるようにする。
//     Normalize HTTP errors into a consistent shape so SWR can surface them as `error`.
//   - 既存挙動を変えないため、JSON 以外のレスポンスでも素直に本文を返す。
//     Keep behavior predictable: fall back to text when the body is not JSON.

import { resilientFetch, type ResilientFetchOptions } from "../../scripts/core/resilient_fetch";

// SWR が error として受け取る、ステータス付きのエラー型。
// An error type carrying the HTTP status so callers can branch on it (e.g. 401 -> login).
export class HttpError extends Error {
  public readonly status: number;
  public readonly info: unknown;

  public constructor(message: string, status: number, info: unknown) {
    super(message);
    this.name = "HttpError";
    this.status = status;
    this.info = info;
  }
}

// レスポンス本文を JSON として解釈する。JSON でなければテキストをそのまま返す。
// Parse the response body as JSON; fall back to raw text when it is not JSON.
async function parseBody(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    try {
      return await response.json();
    } catch {
      return null;
    }
  }
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

export type SwrFetcherInit = RequestInit & { resilient?: ResilientFetchOptions };

/**
 * SWR のキー（URL 文字列）から JSON を取得する汎用フェッチャー。
 * Generic fetcher that resolves a SWR key (URL string) to parsed JSON.
 *
 * 認証付き API のため credentials は既定で同一オリジンを含める。
 * Includes same-origin credentials by default for authenticated APIs.
 */
export async function swrFetcher<Data = unknown>(input: RequestInfo | URL, init?: SwrFetcherInit): Promise<Data> {
  const { resilient, ...requestInit } = init ?? {};
  const response = await resilientFetch(
    input,
    {
      credentials: "same-origin",
      headers: { Accept: "application/json", ...(requestInit.headers || {}) },
      ...requestInit,
    },
    resilient,
  );

  const body = await parseBody(response);

  if (!response.ok) {
    const message =
      (body && typeof body === "object" && "message" in body && typeof (body as { message: unknown }).message === "string"
        ? (body as { message: string }).message
        : null) || `Request failed with status ${response.status}`;
    throw new HttpError(message, response.status, body);
  }

  return body as Data;
}
