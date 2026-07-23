import { resilientFetch } from "../../scripts/core/resilient_fetch";
import { setLoggedInState } from "../../scripts/core/app_state";
import { writeCachedAuthState } from "../../scripts/core/auth_state_cache";
import { memoFetchJsonOrThrow } from "./api";
import type { HttpError } from "./types";
import type {
  ContextCandidateApproveInput,
  ContextCandidateListPayload,
  ContextCandidateMutationPayload,
  ContextCandidateRejectInput,
  ContextCandidateStatus,
  ContextExtractionSettings,
  ContextExtractionSettingsUpdateInput,
  ContextFact,
  ContextFactCandidate,
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

export type ContextCandidateListResult = {
  candidates: ContextFactCandidate[];
  totalPending: number;
  nextCursor: string | null;
};

function createContextApiError(message: string, status: number): HttpError {
  const error = new Error(message) as HttpError;
  error.status = status;
  return error;
}

// 認証切れを空データとして扱わず、ページ間で共有する認証状態にも反映する。
// Do not disguise an expired session as empty data; propagate it to shared auth state.
function handleExpiredContextSession(): never {
  writeCachedAuthState(false);
  if (typeof document !== "undefined") {
    setLoggedInState(false);
  }
  throw createContextApiError(
    "ログインセッションが切れました。再ログインしてください。",
    401,
  );
}

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
  if (res.status === 401) handleExpiredContextSession();
  if (!res.ok) {
    throw createContextApiError(
      data.error || `コンテキストの取得に失敗しました (${res.status})`,
      res.status,
    );
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

// AIが抽出した保存候補を状態・カーソルで取得する。
// Load AI-extracted candidates by status and opaque cursor.
export async function loadContextCandidates(params: {
  status?: ContextCandidateStatus;
  limit?: number;
  cursor?: string | null;
} = {}): Promise<ContextCandidateListResult> {
  const query = new URLSearchParams();
  query.set("status", params.status ?? "pending");
  if (params.limit) query.set("limit", String(params.limit));
  if (params.cursor) query.set("cursor", params.cursor);

  const res = await resilientFetch(`/api/context-facts/candidates?${query.toString()}`, {
    credentials: "same-origin",
  });
  const data: ContextCandidateListPayload = await res.json().catch(() => ({}));
  if (res.status === 401) return { candidates: [], totalPending: 0, nextCursor: null };
  if (!res.ok) {
    throw new Error(data.error || `AIからの提案の取得に失敗しました (${res.status})`);
  }
  return {
    candidates: Array.isArray(data.candidates) ? data.candidates : [],
    totalPending: typeof data.total_pending === "number" ? data.total_pending : 0,
    nextCursor: data.next_cursor ?? null,
  };
}

// 候補を必要に応じて編集し、コンテキスト事実として承認する。
// Approve a candidate as a context fact, optionally with edits.
export async function approveContextCandidate(
  candidateId: number,
  input: ContextCandidateApproveInput,
): Promise<ContextFact | null> {
  const { payload } = await memoFetchJsonOrThrow<ContextCandidateMutationPayload>(
    `/api/context-facts/candidates/${candidateId}/approve`,
    {
      method: "PUT",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
    { defaultMessage: "AIからの提案を承認できませんでした。" },
  );
  return payload.fact ?? null;
}

// 候補を却下し、pending一覧から除外する。
// Reject a candidate and remove it from the pending list.
export async function rejectContextCandidate(
  candidateId: number,
  input: ContextCandidateRejectInput,
): Promise<void> {
  await memoFetchJsonOrThrow<ContextCandidateMutationPayload>(
    `/api/context-facts/candidates/${candidateId}/reject`,
    {
      method: "PUT",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
    { defaultMessage: "AIからの提案を却下できませんでした。" },
  );
}

// 会話からの候補抽出opt-in設定を取得する。
// Load the opt-in setting for candidate extraction from chats.
export async function loadContextExtractionSettings(): Promise<ContextExtractionSettings> {
  const res = await resilientFetch("/api/context-facts/extraction-settings", {
    credentials: "same-origin",
  });
  const data = (await res.json().catch(() => ({}))) as Partial<ContextExtractionSettings> & {
    error?: string;
  };
  if (res.status === 401) return { enabled: false };
  if (!res.ok) {
    throw new Error(data.error || `自動抽出設定の取得に失敗しました (${res.status})`);
  }
  return { enabled: data.enabled === true };
}

// 会話からの候補抽出を明示的に有効化・無効化する。
// Explicitly enable or disable candidate extraction from chats.
export async function updateContextExtractionSettings(
  input: ContextExtractionSettingsUpdateInput,
): Promise<ContextExtractionSettings> {
  const { payload } = await memoFetchJsonOrThrow<ContextExtractionSettings & { error?: string }>(
    "/api/context-facts/extraction-settings",
    {
      method: "PUT",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
    { defaultMessage: "自動抽出設定を更新できませんでした。" },
  );
  return { enabled: payload.enabled === true };
}
