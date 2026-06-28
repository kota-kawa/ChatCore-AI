import { fetchJsonOrThrow } from "../../scripts/core/runtime_validation";
import { resilientFetch } from "../../scripts/core/resilient_fetch";
import type {
  Collection,
  CollectionListPayload,
  HttpError,
  MemoDetailPayload,
  MemoListPayload,
  MemoListState,
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
