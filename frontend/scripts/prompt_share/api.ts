import type { PromptData } from "./types";
import { fetchJsonOrThrow } from "../core/runtime_validation";

type ApiResponse = {
  error?: string;
  message?: string;
  [key: string]: unknown;
};

export async function sendBookmarkRequest(
  method: "POST" | "DELETE",
  payload: Record<string, unknown>
) {
  // ブックマーク系APIの共通処理（HTTP失敗と業務エラーを同じ経路で扱う）
  // Shared bookmark API helper handling both HTTP and business-level errors.
  const { payload: data } = await fetchJsonOrThrow<ApiResponse>(
    "/prompt_share/api/bookmark",
    {
      method,
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }
  );
  return data;
}

export function savePromptBookmark(prompt: PromptData) {
  return sendBookmarkRequest("POST", {
    title: prompt.title,
    content: prompt.content,
    input_examples: prompt.input_examples || "",
    output_examples: prompt.output_examples || ""
  });
}

export function removePromptBookmark(prompt: PromptData) {
  return sendBookmarkRequest("DELETE", {
    title: prompt.title
  });
}

export function savePromptToList(prompt: PromptData) {
  // 保存対象IDが無い場合はAPI呼び出し前に明確なエラーを返す
  // Fail fast before API call when prompt ID is missing.
  if (prompt.id === undefined || prompt.id === null) {
    return Promise.reject(new Error("保存対象のプロンプトIDが見つかりません。"));
  }

  return fetchJsonOrThrow<ApiResponse>("/prompt_share/api/prompt_list", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      prompt_id: prompt.id
    })
  }).then(({ payload }) => payload);
}

export function fetchPromptList() {
  return fetchJsonOrThrow<{ prompts?: PromptData[] }>("/prompt_share/api/prompts", undefined, {
    defaultMessage: "プロンプト一覧の取得に失敗しました。"
  }).then(({ payload }) => payload);
}

export function fetchPromptSearchResults(query: string) {
  return fetchJsonOrThrow<{ prompts?: PromptData[] }>(
    `/search/prompts?q=${encodeURIComponent(query)}`,
    undefined,
    {
      defaultMessage: "検索に失敗しました。"
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
