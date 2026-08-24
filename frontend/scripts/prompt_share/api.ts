import type {
  ContentFormat,
  MediaType,
  PromptAuthorProfileResponse,
  PromptCommentsResponse,
  PromptCreateResponse,
  PromptData,
  PromptFeedResponse,
  PromptViewResponse,
  PromptType
} from "./types";
import { fetchJsonOrThrow } from "../core/runtime_validation";
import { resilientFetch } from "../core/resilient_fetch";
import { promptShareText } from "./i18n";

type ApiResponse = {
  error?: string;
  message?: string;
  [key: string]: unknown;
};

function promptShareFetchJsonOrThrow<TPayload>(
  input: RequestInfo | URL,
  init?: RequestInit,
  options?: Parameters<typeof fetchJsonOrThrow<TPayload>>[2],
) {
  return fetchJsonOrThrow<TPayload>(input, init, {
    ...options,
    fetchImpl: resilientFetch,
  });
}

export async function sendLikeRequest(method: "POST" | "DELETE", prompt: PromptData) {
  if (prompt.id === undefined || prompt.id === null) {
    return Promise.reject(new Error(promptShareText("promptShare.likeTargetMissing")));
  }

  const { payload } = await promptShareFetchJsonOrThrow<ApiResponse>("/prompt_share/api/like", {
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
  return promptShareFetchJsonOrThrow<PromptCommentsResponse>(
    `/prompt_share/api/prompts/${encodeURIComponent(String(promptId))}/comments`,
    undefined,
    {
      defaultMessage: promptShareText("promptShare.loadCommentsFailed")
    }
  ).then(({ payload }) => payload);
}

export function recordPromptView(promptId: string | number) {
  return promptShareFetchJsonOrThrow<PromptViewResponse>(
    `/prompt_share/api/prompts/${encodeURIComponent(String(promptId))}/view`,
    {
      method: "POST",
      credentials: "same-origin"
    },
    {
      defaultMessage: promptShareText("promptShare.loadFailed")
    }
  ).then(({ payload }) => payload);
}

export function createPromptComment(promptId: string | number, content: string) {
  return promptShareFetchJsonOrThrow<PromptCommentsResponse>(
    `/prompt_share/api/prompts/${encodeURIComponent(String(promptId))}/comments`,
    {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content })
    },
    {
      defaultMessage: promptShareText("promptShare.commentPostFailed")
    }
  ).then(({ payload }) => payload);
}

export function deletePromptComment(commentId: string | number) {
  return promptShareFetchJsonOrThrow<PromptCommentsResponse>(
    `/prompt_share/api/comments/${encodeURIComponent(String(commentId))}`,
    {
      method: "DELETE",
      credentials: "same-origin"
    },
    {
      defaultMessage: promptShareText("promptShare.commentDeleteFailed")
    }
  ).then(({ payload }) => payload);
}

export function reportPromptComment(
  commentId: string | number,
  reason: "spam" | "harassment" | "abuse" | "other" = "abuse",
  details = ""
) {
  return promptShareFetchJsonOrThrow<PromptCommentsResponse>(
    `/prompt_share/api/comments/${encodeURIComponent(String(commentId))}/report`,
    {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason, details })
    },
    {
      defaultMessage: promptShareText("promptShare.commentReportFailed")
    }
  ).then(({ payload }) => payload);
}

export function addPromptAsTask(prompt: PromptData) {
  // タスク追加対象IDが無い場合はAPI呼び出し前に明確なエラーを返す
  // Fail fast before API call when prompt ID is missing.
  if (prompt.id === undefined || prompt.id === null) {
    return Promise.reject(new Error(promptShareText("promptShare.useTargetMissing")));
  }

  return promptShareFetchJsonOrThrow<ApiResponse>("/prompt_share/api/task", {
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
    return Promise.reject(new Error(promptShareText("promptShare.removeUseTargetMissing")));
  }

  return promptShareFetchJsonOrThrow<ApiResponse>("/prompt_share/api/task", {
    method: "DELETE",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      prompt_id: prompt.id
    })
  }).then(({ payload }) => payload);
}

// 共有プロンプトの実体をメモ本文として保存する。SKILL は定義本文を優先する。
// Saves the shared prompt's actual body as a memo, preferring the SKILL definition for SKILL posts.
export function savePromptAsMemo(prompt: PromptData) {
  const promptContent = String(prompt.content || "").trim();
  const skillContent = String(prompt.skill_markdown || "").trim();
  const memoContent = prompt.content_format === "skill"
    ? skillContent || promptContent
    : promptContent || skillContent;

  if (!memoContent) {
    return Promise.reject(new Error(promptShareText("promptShare.memoContentMissing")));
  }

  return promptShareFetchJsonOrThrow<ApiResponse>(
    "/memo/api",
    {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ai_response: memoContent,
        title: String(prompt.title || "").trim()
      })
    },
    {
      defaultMessage: promptShareText("promptShare.saveMemoFailed"),
      hasApplicationError: (payload) => payload.status === "fail"
    }
  ).then(({ payload }) => payload);
}

export function fetchPromptList(options?: {
  limit?: number;
  cursor?: string | null;
  category?: string;
  contentFormat?: ContentFormat | "all";
  mediaType?: MediaType | "all";
  authorId?: number | string;
}) {
  const params = new URLSearchParams();
  if (options?.limit) {
    params.set("limit", String(options.limit));
  }
  if (options?.cursor) {
    params.set("cursor", options.cursor);
  }
  if (options?.category && options.category !== "all") {
    params.set("category", options.category);
  }
  if (options?.contentFormat && options.contentFormat !== "all") {
    params.set("content_format", options.contentFormat);
  }
  if (options?.mediaType && options.mediaType !== "all") {
    params.set("media_type", options.mediaType);
  }
  if (options?.authorId !== undefined && options.authorId !== null && options.authorId !== "") {
    params.set("author_id", String(options.authorId));
  }
  const query = params.toString();

  return promptShareFetchJsonOrThrow<PromptFeedResponse>(
    `/prompt_share/api/prompts${query ? `?${query}` : ""}`,
    undefined,
    {
      defaultMessage: promptShareText("promptShare.loadFailed")
    }
  ).then(({ payload }) => payload);
}

// SNS風プロフィールモーダル向けに、投稿者の公開プロフィール（アバター・自己紹介・投稿数）を取得する
// Fetches an author's public profile (avatar, bio, post count) for the SNS-style profile modal
export function fetchPromptAuthorProfile(userId: number | string) {
  return promptShareFetchJsonOrThrow<PromptAuthorProfileResponse>(
    `/prompt_share/api/users/${encodeURIComponent(String(userId))}`,
    undefined,
    {
      defaultMessage: promptShareText("promptShare.authorProfileLoadFailed")
    }
  ).then(({ payload }) => payload);
}

export function fetchPromptSearchResults(
  query: string,
  options?: {
    page?: number;
    perPage?: number;
    includeTotal?: boolean;
    promptType?: PromptType | "all";
    contentFormat?: ContentFormat | "all";
    mediaType?: MediaType | "all";
  }
) {
  const params = new URLSearchParams({ q: query });
  if (options?.page) {
    params.set("page", String(options.page));
  }
  if (options?.perPage) {
    params.set("per_page", String(options.perPage));
  }
  if (options?.includeTotal === false) {
    params.set("include_total", "0");
  }
  if (options?.promptType && options.promptType !== "all") {
    params.set("prompt_type", options.promptType);
  }
  if (options?.contentFormat && options.contentFormat !== "all") {
    params.set("content_format", options.contentFormat);
  }
  if (options?.mediaType && options.mediaType !== "all") {
    params.set("media_type", options.mediaType);
  }

  return promptShareFetchJsonOrThrow<PromptFeedResponse>(
    `/search/prompts?${params.toString()}`,
    undefined,
    {
      defaultMessage: promptShareText("promptShare.searchFailed")
    }
  ).then(({ payload }) => payload);
}

export async function createPrompt(postData: FormData): Promise<PromptCreateResponse> {
  // FormData は multipart 送信になるため Content-Type は自動設定に任せる
  // Let browser set multipart Content-Type automatically for FormData.
  const { payload } = await promptShareFetchJsonOrThrow<PromptCreateResponse>(
    "/prompt_share/api/prompts",
    {
      method: "POST",
      body: postData
    },
    {
      defaultMessage: promptShareText("promptShare.postFailed")
    }
  );
  return payload;
}
