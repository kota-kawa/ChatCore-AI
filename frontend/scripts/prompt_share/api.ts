import type { PromptData } from "./types";

type ApiResponse = {
  error?: string;
  message?: string;
  [key: string]: unknown;
};

export function sendBookmarkRequest(method: "POST" | "DELETE", payload: Record<string, unknown>) {
  return fetch("/prompt_share/api/bookmark", {
    method,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  }).then(async (response) => {
    const data = (await response.json().catch(() => ({}))) as ApiResponse;
    if (!response.ok || data.error) {
      throw new Error(data.error || "操作に失敗しました。");
    }
    return data;
  });
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
  if (prompt.id === undefined || prompt.id === null) {
    return Promise.reject(new Error("保存対象のプロンプトIDが見つかりません。"));
  }

  return fetch("/prompt_share/api/prompt_list", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      prompt_id: prompt.id
    })
  }).then(async (response) => {
    const data = (await response.json().catch(() => ({}))) as ApiResponse;
    if (!response.ok || data.error) {
      throw new Error(data.error || "操作に失敗しました。");
    }
    return data;
  });
}

export function fetchPromptList() {
  return fetch("/prompt_share/api/prompts").then((response) => {
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    return response.json() as Promise<{ prompts?: PromptData[] }>;
  });
}

export function fetchPromptSearchResults(query: string) {
  return fetch(`/search/prompts?q=${encodeURIComponent(query)}`).then((response) => {
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    return response.json() as Promise<{ prompts?: PromptData[] }>;
  });
}

export async function createPrompt(postData: FormData) {
  const response = await fetch("/prompt_share/api/prompts", {
    method: "POST",
    body: postData
  });
  const result = (await response.json().catch(() => ({}))) as ApiResponse;
  if (!response.ok || result.error) {
    throw new Error(result.error || "プロンプト投稿中にエラーが発生しました。");
  }
  return result;
}
