import assert from "node:assert/strict";
import test from "node:test";

import { fetchPromptAuthorProfile, fetchPromptList } from "../scripts/prompt_share/api";

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
