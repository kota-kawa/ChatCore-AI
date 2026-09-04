import { fetchJsonOrThrow } from "../../scripts/core/runtime_validation";
import { resilientFetch } from "../../scripts/core/resilient_fetch";
import type {
  BulkMemoActionInput,
  Collection,
  CollectionInput,
  CollectionListPayload,
  HttpError,
  MemoComposeFormState,
  MemoDetail,
  MemoDetailPayload,
  MemoExportFormat,
  MemoListPayload,
  MemoListState,
  MemoReorderInput,
  MemoSuggestPayload,
  MemoUpdateInput,
  SharePayload,
} from "./types";

// ---------------------------------------------------------------------------
// Memo page data fetching
// ---------------------------------------------------------------------------

// 指定されたURLからメモ一覧を読み込む非同期関数
// Async function to load the memo list from the specified URL
export const loadMemoList = async (url: string): Promise<MemoListState> => {
  const res = await resilientFetch(url, { credentials: "same-origin" });
  const data: MemoListPayload = await res.json().catch(() => ({}));
  if (res.status === 401) return { memos: [], total: 0 };
  if (!res.ok) {
    const error = new Error(data.error || `メモの取得に失敗しました (${res.status})`) as HttpError;
    (error as HttpError).status = res.status;
    throw error;
  }
  return {
    memos: Array.isArray(data.memos) ? data.memos : [],
    total: typeof data.total === "number" ? data.total : 0,
  };
};

// メモのコレクション（タグ/フォルダ）一覧を読み込む非同期関数
// Async function to load the list of memo collections (tags/folders)
export const loadCollections = async (): Promise<Collection[]> => {
  const res = await resilientFetch("/memo/api/collections", { credentials: "same-origin" });
  const data: CollectionListPayload = await res.json().catch(() => ({}));
  if (!res.ok) return [];
  return Array.isArray(data.collections) ? data.collections : [];
};

// メモのIDから詳細情報を取得する非同期関数
// Async function to load memo detail from its ID
export async function loadMemoDetail(memoId: string | number) {
  const { payload } = await memoFetchJsonOrThrow<MemoDetailPayload>(
    `/memo/api/${memoId}`,
    { credentials: "same-origin" },
    { defaultMessage: "メモの詳細取得に失敗しました。", hasApplicationError: (d) => !d.memo },
  );
  return payload.memo || null;
}

export function memoFetchJsonOrThrow<TPayload>(
  input: RequestInfo | URL,
  init?: RequestInit,
  options?: Parameters<typeof fetchJsonOrThrow<TPayload>>[2],
) {
  return fetchJsonOrThrow<TPayload>(input, init, {
    ...options,
    fetchImpl: resilientFetch,
  });
}

// ---------------------------------------------------------------------------
// Memo page mutations
// /memo/api/* への変更系リクエストの型付きラッパー。エラーは throw するだけで、
// 表示（flash など）は呼び出し側の hook が担当する。
// Typed wrappers around the /memo/api/* mutation endpoints. They only throw;
// surfacing the error (flash messages etc.) is the calling hook's job.
// ---------------------------------------------------------------------------

const JSON_HEADERS = { "Content-Type": "application/json" };

// メモを新規作成する
// Create a new memo
export async function createMemo(input: MemoComposeFormState, defaultMessage: string): Promise<void> {
  await memoFetchJsonOrThrow(
    "/memo/api",
    { method: "POST", headers: JSON_HEADERS, credentials: "same-origin", body: JSON.stringify(input) },
    { defaultMessage },
  );
}

// 本文から AI にタイトル候補を提案させる
// Ask the AI for a title suggestion based on the body text
export async function suggestMemoTitle(aiResponse: string, defaultMessage: string): Promise<MemoSuggestPayload> {
  const { payload } = await memoFetchJsonOrThrow<MemoSuggestPayload>(
    "/memo/api/suggest",
    { method: "POST", headers: JSON_HEADERS, credentials: "same-origin", body: JSON.stringify({ ai_response: aiResponse }) },
    { defaultMessage },
  );
  return payload;
}

// メモの内容を更新し、サーバーが返した最新のメモを返す
// Update a memo and return the server's view of it
export async function updateMemo(
  memoId: string | number,
  input: MemoUpdateInput,
  defaultMessage: string,
): Promise<MemoDetail | undefined> {
  const { payload } = await memoFetchJsonOrThrow<MemoDetailPayload>(
    `/memo/api/${memoId}`,
    { method: "PATCH", headers: JSON_HEADERS, credentials: "same-origin", body: JSON.stringify(input) },
    { defaultMessage, hasApplicationError: (data) => !data.memo },
  );
  return payload.memo;
}

// メモを削除する
// Delete a memo
export async function deleteMemo(memoId: string | number, defaultMessage: string): Promise<void> {
  await memoFetchJsonOrThrow(`/memo/api/${memoId}`, { method: "DELETE", credentials: "same-origin" }, { defaultMessage });
}

// ピン留め状態を設定する
// Set the pinned state
export async function setMemoPinned(memoId: string | number, enabled: boolean, defaultMessage: string): Promise<void> {
  await memoFetchJsonOrThrow(
    `/memo/api/${memoId}/pin`,
    { method: "POST", headers: JSON_HEADERS, credentials: "same-origin", body: JSON.stringify({ enabled }) },
    { defaultMessage },
  );
}

// アーカイブ状態を設定する
// Set the archived state
export async function setMemoArchived(memoId: string | number, enabled: boolean, defaultMessage: string): Promise<void> {
  await memoFetchJsonOrThrow(
    `/memo/api/${memoId}/archive`,
    { method: "POST", headers: JSON_HEADERS, credentials: "same-origin", body: JSON.stringify({ enabled }) },
    { defaultMessage },
  );
}

// 手動並び順を保存する（before/after は隣接メモの ID）
// Persist the manual order (before/after are the neighbouring memo ids)
export async function reorderMemos(input: MemoReorderInput, defaultMessage: string): Promise<void> {
  await memoFetchJsonOrThrow(
    "/memo/api/reorder",
    { method: "POST", headers: JSON_HEADERS, credentials: "same-origin", body: JSON.stringify(input) },
    { defaultMessage },
  );
}

// 複数メモへの一括操作を実行する
// Run a bulk action over several memos
export async function runBulkMemoAction(input: BulkMemoActionInput, defaultMessage: string): Promise<void> {
  await memoFetchJsonOrThrow(
    "/memo/api/bulk",
    { method: "POST", headers: JSON_HEADERS, credentials: "same-origin", body: JSON.stringify(input) },
    { defaultMessage },
  );
}

// メモの現在の共有状態を取得する
// Fetch the memo's current share state
export async function fetchMemoShare(memoId: string | number, defaultMessage: string): Promise<SharePayload> {
  const { payload } = await memoFetchJsonOrThrow<SharePayload>(
    `/memo/api/${memoId}/share`,
    { credentials: "same-origin" },
    { defaultMessage },
  );
  return payload;
}

// 共有リンクを作成（既存があれば再利用）する
// Create the share link (reusing an existing active one)
export async function createMemoShare(memoId: string | number, defaultMessage: string): Promise<SharePayload> {
  const { payload } = await memoFetchJsonOrThrow<SharePayload>(
    `/memo/api/${memoId}/share`,
    {
      method: "POST",
      headers: JSON_HEADERS,
      credentials: "same-origin",
      body: JSON.stringify({ force_refresh: false, expires_in_days: 30 }),
    },
    { defaultMessage },
  );
  return payload;
}

// コレクションを作成する
// Create a collection
export async function createCollection(input: CollectionInput, defaultMessage: string): Promise<void> {
  await memoFetchJsonOrThrow(
    "/memo/api/collections",
    { method: "POST", headers: JSON_HEADERS, credentials: "same-origin", body: JSON.stringify(input) },
    { defaultMessage },
  );
}

// コレクションの名前・色を更新する
// Rename / recolor a collection
export async function updateCollection(collectionId: number, input: CollectionInput, defaultMessage: string): Promise<void> {
  await memoFetchJsonOrThrow(
    `/memo/api/collections/${collectionId}`,
    { method: "PATCH", headers: JSON_HEADERS, credentials: "same-origin", body: JSON.stringify(input) },
    { defaultMessage },
  );
}

// コレクションを削除する
// Delete a collection
export async function deleteCollection(collectionId: number, defaultMessage: string): Promise<void> {
  await memoFetchJsonOrThrow(
    `/memo/api/collections/${collectionId}`,
    { method: "DELETE", credentials: "same-origin" },
    { defaultMessage },
  );
}

// エクスポート用 URL を組み立てる（ids が空なら全件）
// Build the export download URL (all memos when ids is empty)
export function buildMemoExportUrl(format: MemoExportFormat, ids: string[]): string {
  const params = new URLSearchParams({ format });
  const joined = ids.join(",");
  if (joined) params.set("ids", joined);
  return `/memo/api/export?${params.toString()}`;
}
