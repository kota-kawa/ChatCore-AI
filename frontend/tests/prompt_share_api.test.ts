import assert from "node:assert/strict";
import test from "node:test";

import {
  createPrompt,
  fetchPromptAuthorProfile,
  fetchPromptList,
  recordPromptView,
  savePromptAsMemo
} from "../scripts/prompt_share/api";

const originalFetch = globalThis.fetch;

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" }
  });
}

test("fetchPromptList sends cursor pagination and server-side filters", async () => {
  let requestedUrl = "";
  globalThis.fetch = (async (input) => {
    requestedUrl = String(input);
    return jsonResponse({ prompts: [], pagination: { has_next: false } });
  }) as typeof fetch;

  try {
    await fetchPromptList({
      limit: 24,
      cursor: "cursor/value+safe",
      category: "business",
      contentFormat: "prompt",
      mediaType: "image"
    });
  } finally {
    globalThis.fetch = originalFetch;
  }

  const parsed = new URL(requestedUrl, "https://example.com");
  assert.equal(parsed.pathname, "/prompt_share/api/prompts");
  assert.equal(parsed.searchParams.get("limit"), "24");
  assert.equal(parsed.searchParams.get("cursor"), "cursor/value+safe");
  assert.equal(parsed.searchParams.get("category"), "business");
  assert.equal(parsed.searchParams.get("content_format"), "prompt");
  assert.equal(parsed.searchParams.get("media_type"), "image");
});

test("fetchPromptList omits all-valued filters from the query string", async () => {
  let requestedUrl = "";
  globalThis.fetch = (async (input) => {
    requestedUrl = String(input);
    return jsonResponse({ prompts: [] });
  }) as typeof fetch;

  try {
    await fetchPromptList({
      category: "all",
      contentFormat: "all",
      mediaType: "all"
    });
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(requestedUrl, "/prompt_share/api/prompts");
});

// SNS風プロフィール表示向けに、authorIdがクエリ文字列へ渡されることを検証する
// Verifies authorId is forwarded to the query string, for the SNS-style profile view
test("fetchPromptList forwards authorId as the author_id query parameter", async () => {
  let requestedUrl = "";
  globalThis.fetch = (async (input) => {
    requestedUrl = String(input);
    return jsonResponse({ prompts: [], pagination: { has_next: false } });
  }) as typeof fetch;

  try {
    await fetchPromptList({ authorId: 42, limit: 10 });
  } finally {
    globalThis.fetch = originalFetch;
  }

  const parsed = new URL(requestedUrl, "https://example.com");
  assert.equal(parsed.searchParams.get("author_id"), "42");
  assert.equal(parsed.searchParams.get("limit"), "10");
});

test("fetchPromptAuthorProfile requests the author profile endpoint by user ID", async () => {
  let requestedUrl = "";
  globalThis.fetch = (async (input) => {
    requestedUrl = String(input);
    return jsonResponse({
      status: "success",
      user: { id: 42, username: "Kota", avatar_url: "", bio: "", prompt_count: 2 }
    });
  }) as typeof fetch;

  let payload;
  try {
    payload = await fetchPromptAuthorProfile(42);
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(requestedUrl, "/prompt_share/api/users/42");
  assert.equal(payload.user?.username, "Kota");
});

test("recordPromptView posts to the prompt detail view endpoint", async () => {
  let requestedUrl = "";
  let requestedInit: RequestInit | undefined;
  globalThis.fetch = (async (input, init) => {
    requestedUrl = String(input);
    requestedInit = init;
    return jsonResponse({ status: "success", view_count: 6 });
  }) as typeof fetch;

  let payload;
  try {
    payload = await recordPromptView(42);
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(requestedUrl, "/prompt_share/api/prompts/42/view");
  assert.equal(requestedInit?.method, "POST");
  assert.equal(requestedInit?.credentials, "same-origin");
  assert.equal(payload.view_count, 6);
});

test("createPrompt returns the guest-post marker from the API", async () => {
  let requestedUrl = "";
  let requestedInit: RequestInit | undefined;
  globalThis.fetch = (async (input, init) => {
    requestedUrl = String(input);
    requestedInit = init;
    return jsonResponse({ message: "created", prompt_id: 19, is_guest: true });
  }) as typeof fetch;

  let payload;
  try {
    payload = await createPrompt(new FormData());
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(requestedUrl, "/prompt_share/api/prompts");
  assert.equal(requestedInit?.method, "POST");
  assert.equal(payload.is_guest, true);
  assert.equal(payload.prompt_id, 19);
});

test("savePromptAsMemo saves the shared prompt title and body through the memo API", async () => {
  let requestedUrl = "";
  let requestedInit: RequestInit | undefined;
  globalThis.fetch = (async (input, init) => {
    requestedUrl = String(input);
    requestedInit = init;
    return jsonResponse({ status: "success", memo_id: 21 });
  }) as typeof fetch;

  try {
    await savePromptAsMemo({
      id: 7,
      title: "設計レビューの観点",
      content: "設計をレビューして、懸念点を列挙してください。",
      content_format: "prompt"
    });
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(requestedUrl, "/memo/api");
  assert.equal(requestedInit?.method, "POST");
  assert.equal(requestedInit?.credentials, "same-origin");
  assert.deepEqual(JSON.parse(String(requestedInit?.body)), {
    ai_response: "設計をレビューして、懸念点を列挙してください。",
    title: "設計レビューの観点"
  });
});

test("savePromptAsMemo prefers skill_markdown for SKILL posts", async () => {
  let requestedBody = "";
  globalThis.fetch = (async (_input, init) => {
    requestedBody = String(init?.body || "");
    return jsonResponse({ status: "success", memo_id: 22 });
  }) as typeof fetch;

  try {
    await savePromptAsMemo({
      id: 8,
      title: "レビュー SKILL",
      content: "一覧用の説明",
      content_format: "skill",
      skill_markdown: "# Review SKILL\n\n## Steps\n1. Check the design"
    });
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(
    JSON.parse(requestedBody).ai_response,
    "# Review SKILL\n\n## Steps\n1. Check the design"
  );
});
