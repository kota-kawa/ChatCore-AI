import type {
  PromptCommentsResponse,
  PromptData,
  PromptFeedResponse,
  PromptType
} from "./types";
import { fetchJsonOrThrow } from "../core/runtime_validation";
import { resilientFetch } from "../core/resilient_fetch";

type ApiResponse = {
  error?: string;
  message?: string;
  [key: string]: unknown;
};

export async function sendLikeRequest(method: "POST" | "DELETE", prompt: PromptData) {
  if (prompt.id === undefined || prompt.id === null) {
    return Promise.reject(new Error("いいね対象のプロンプトIDが見つかりません。"));
  }

  const { payload } = await fetchJsonOrThrow<ApiResponse>("/prompt_share/api/like", {
    method,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      prompt_id: prompt.id
    })
  });
  return payload;
}

export function savePromptLike(prompt: PromptData) {
  return sendLikeRequest("POST", prompt);
}

export function removePromptLike(prompt: PromptData) {
  return sendLikeRequest("DELETE", prompt);
}

export function fetchPromptComments(promptId: string | number) {
  return fetchJsonOrThrow<PromptCommentsResponse>(
    `/prompt_share/api/prompts/${encodeURIComponent(String(promptId))}/comments`,
    undefined,
    {
      defaultMessage: "コメント一覧の取得に失敗しました。"
    }
  ).then(({ payload }) => payload);
}

export function createPromptComment(promptId: string | number, content: string) {
  return fetchJsonOrThrow<PromptCommentsResponse>(
    `/prompt_share/api/prompts/${encodeURIComponent(String(promptId))}/comments`,
    {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content })
    },
    {
      defaultMessage: "コメント投稿に失敗しました。"
    }
  ).then(({ payload }) => payload);
}

export function deletePromptComment(commentId: string | number) {
  return fetchJsonOrThrow<PromptCommentsResponse>(
    `/prompt_share/api/comments/${encodeURIComponent(String(commentId))}`,
    {
      method: "DELETE",
      credentials: "same-origin"
    },
    {
      defaultMessage: "コメント削除に失敗しました。"
    }
  ).then(({ payload }) => payload);
}

export function reportPromptComment(
  commentId: string | number,
  reason: "spam" | "harassment" | "abuse" | "other" = "abuse",
  details = ""
) {
  return fetchJsonOrThrow<PromptCommentsResponse>(
    `/prompt_share/api/comments/${encodeURIComponent(String(commentId))}/report`,
    {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason, details })
    },
    {
      defaultMessage: "コメント報告に失敗しました。"
    }
  ).then(({ payload }) => payload);
}

export function addPromptAsTask(prompt: PromptData) {
  // タスク追加対象IDが無い場合はAPI呼び出し前に明確なエラーを返す
  // Fail fast before API call when prompt ID is missing.
  if (prompt.id === undefined || prompt.id === null) {
    return Promise.reject(new Error("チャットで使う対象のプロンプトIDが見つかりません。"));
  }

  return fetchJsonOrThrow<ApiResponse>("/prompt_share/api/task", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      prompt_id: prompt.id
    })
  }).then(({ payload }) => payload);
}

export function removePromptAsTask(prompt: PromptData) {
  // タスク解除対象IDが無い場合はAPI呼び出し前に明確なエラーを返す
  // Fail fast before API call when prompt ID is missing.
  if (prompt.id === undefined || prompt.id === null) {
    return Promise.reject(new Error("チャットで使う解除対象のプロンプトIDが見つかりません。"));
  }

  return fetchJsonOrThrow<ApiResponse>("/prompt_share/api/task", {
    method: "DELETE",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      prompt_id: prompt.id
    })
  }).then(({ payload }) => payload);
}

export function fetchPromptList() {
  return fetchJsonOrThrow<PromptFeedResponse>("/prompt_share/api/prompts", undefined, {
    defaultMessage: "プロンプト一覧の取得に失敗しました。",
    fetchImpl: resilientFetch
  }).then(({ payload }) => payload);
}

export function fetchPromptSearchResults(
  query: string,
  options?: { page?: number; perPage?: number; promptType?: PromptType | "all" }
) {
  const params = new URLSearchParams({ q: query });
  if (options?.page) {
    params.set("page", String(options.page));
  }
  if (options?.perPage) {
    params.set("per_page", String(options.perPage));
  }
  if (options?.promptType && options.promptType !== "all") {
    params.set("prompt_type", options.promptType);
  }

  return fetchJsonOrThrow<PromptFeedResponse>(
    `/search/prompts?${params.toString()}`,
    undefined,
    {
      defaultMessage: "検索に失敗しました。",
      fetchImpl: resilientFetch
    }
  ).then(({ payload }) => payload);
}

export async function createPrompt(postData: FormData) {
  // FormData は multipart 送信になるため Content-Type は自動設定に任せる
  // Let browser set multipart Content-Type automatically for FormData.
  const { payload } = await fetchJsonOrThrow<ApiResponse>(
    "/prompt_share/api/prompts",
    {
      method: "POST",
      body: postData
    },
    {
      defaultMessage: "プロンプト投稿中にエラーが発生しました。"
    }
  );
  return payload;
}
