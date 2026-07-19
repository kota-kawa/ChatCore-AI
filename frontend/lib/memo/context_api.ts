import { resilientFetch } from "../../scripts/core/resilient_fetch";
import { memoFetchJsonOrThrow } from "./api";
import type {
  ContextFact,
  ContextFactCreateInput,
  ContextFactListPayload,
  ContextFactMutationPayload,
  ContextFactStatus,
  ContextFactType,
  ContextFactUpdateInput,
} from "./context_types";

export type ContextFactListResult = {
  facts: ContextFact[];
  totalActive: number;
  nextCursor: string | null;
};

// マイコンテキスト一覧を種類・状態で絞り込んで取得する。
// Load the context vault list, filtered by fact type / status.
export async function loadContextFacts(params: {
  factType?: ContextFactType | null;
  status?: ContextFactStatus;
  cursor?: string | null;
}): Promise<ContextFactListResult> {
  const query = new URLSearchParams();
  if (params.factType) query.set("fact_type", params.factType);
  query.set("status", params.status ?? "active");
  if (params.cursor) query.set("cursor", params.cursor);

  const res = await resilientFetch(`/api/context-facts?${query.toString()}`, {
    credentials: "same-origin",
  });
  const data: ContextFactListPayload = await res.json().catch(() => ({}));
  if (res.status === 401) return { facts: [], totalActive: 0, nextCursor: null };
  if (!res.ok) {
    throw new Error(data.error || `コンテキストの取得に失敗しました (${res.status})`);
  }
  return {
    facts: Array.isArray(data.facts) ? data.facts : [],
    totalActive: typeof data.total_active === "number" ? data.total_active : 0,
    nextCursor: data.next_cursor ?? null,
  };
}

// マイコンテキストを新規作成する。
// Create a new context fact.
export async function createContextFact(input: ContextFactCreateInput): Promise<ContextFact> {
  const { payload } = await memoFetchJsonOrThrow<ContextFactMutationPayload>(
    "/api/context-facts",
    {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
    { defaultMessage: "コンテキストの保存に失敗しました。", hasApplicationError: (d) => !d.fact },
  );
  return payload.fact as ContextFact;
}

// マイコンテキストを更新する（無効化・復元も status で行う）。
// Update a context fact (deprecate/restore handled via status).
export async function updateContextFact(
  factId: number,
  input: ContextFactUpdateInput,
): Promise<ContextFact> {
  const { payload } = await memoFetchJsonOrThrow<ContextFactMutationPayload>(
    `/api/context-facts/${factId}`,
    {
      method: "PUT",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
    { defaultMessage: "コンテキストの更新に失敗しました。", hasApplicationError: (d) => !d.fact },
  );
  return payload.fact as ContextFact;
}
