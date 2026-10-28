import { useCallback, useState } from "react";
import useSWR from "swr";
import type { z } from "zod";

import { resilientFetch } from "../scripts/core/resilient_fetch";
import {
  DemoAccessCodeIssueResponseSchema,
  DemoAccessCodeListResponseSchema,
  DemoAccessCodeRevokeResponseSchema,
  type DemoAccessCodeApi
} from "../types/generated/api_schemas";

const DEMO_CODES_URL = "/admin/api/demo-codes";

// 管理者セッションが切れたことを呼び出し側（ログイン画面へ戻す役）に伝えるエラー
// Error telling the caller (which sends the admin back to the login page) that the admin session is gone
export class DemoCodesUnauthorizedError extends Error {}

// 管理 API を呼び、401 は専用エラー、失敗はサーバーの文言付きのエラーにして、成功時はスキーマで検証して返す
// Call the admin API: 401 becomes a dedicated error, failures carry the server's message, and a success is validated with the schema
async function requestDemoCodes<TSchema extends z.ZodTypeAny>(
  url: string,
  schema: TSchema,
  fallbackMessage: string,
  init?: RequestInit
): Promise<z.infer<TSchema>> {
  const response = await resilientFetch(url, { credentials: "same-origin", ...init });
  const body: unknown = await response.json().catch(() => ({}));
  if (response.status === 401) throw new DemoCodesUnauthorizedError();
  const record = typeof body === "object" && body !== null ? (body as Record<string, unknown>) : {};
  if (!response.ok || record.status === "fail") {
    throw new Error(typeof record.error === "string" && record.error ? record.error : fallbackMessage);
  }
  const parsed = schema.safeParse(body);
  if (!parsed.success) throw new Error(fallbackMessage);
  return parsed.data;
}

type DemoCodeMessages = { loadFailed: string; issueFailed: string; revokeFailed: string };

// 管理画面の「デモ用アクセスコード」の一覧・発行・停止を扱うフック
// Hook for listing, issuing and stopping demo access codes on the admin page
export function useDemoAccessCodes(messages: DemoCodeMessages) {
  const { data, error, isLoading, mutate } = useSWR<DemoAccessCodeApi[], Error>(
    DEMO_CODES_URL,
    async (url: string) => (await requestDemoCodes(url, DemoAccessCodeListResponseSchema, messages.loadFailed)).codes,
    { revalidateOnFocus: true }
  );
  const [issuing, setIssuing] = useState(false);
  const [revokingId, setRevokingId] = useState<number | null>(null);

  // 発行した直後のレスポンスにだけコードの平文が含まれる。呼び出し側が表示後に捨てる
  // Only the response right after issuing carries the plain code; the caller drops it after showing it
  const issue = useCallback(
    async (label: string) => {
      setIssuing(true);
      try {
        const result = await requestDemoCodes(DEMO_CODES_URL, DemoAccessCodeIssueResponseSchema, messages.issueFailed, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ label })
        });
        await mutate();
        return result;
      } finally {
        setIssuing(false);
      }
    },
    [messages.issueFailed, mutate]
  );

  const revoke = useCallback(
    async (id: number) => {
      setRevokingId(id);
      try {
        await requestDemoCodes(`${DEMO_CODES_URL}/${id}/revoke`, DemoAccessCodeRevokeResponseSchema, messages.revokeFailed, {
          method: "POST"
        });
        await mutate();
      } finally {
        setRevokingId(null);
      }
    },
    [messages.revokeFailed, mutate]
  );

  return { codes: data ?? [], error, isLoading, issuing, revokingId, issue, revoke };
}
