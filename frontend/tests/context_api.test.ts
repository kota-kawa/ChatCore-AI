import assert from "node:assert/strict";
import test from "node:test";

import { loadContextFacts } from "../lib/memo/context_api";

const originalFetch = globalThis.fetch;

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

test("loadContextFacts sends filters and an opaque cursor", async () => {
  let requestedUrl = "";
  globalThis.fetch = (async (input) => {
    requestedUrl = String(input);
    return jsonResponse({ facts: [], total_active: 12, next_cursor: "next/value+safe" });
  }) as typeof fetch;

  try {
    const result = await loadContextFacts({
      factType: "project",
      status: "deprecated",
      cursor: "cursor/value+safe",
    });

    const parsed = new URL(requestedUrl, "https://example.com");
    assert.equal(parsed.pathname, "/api/context-facts");
    assert.equal(parsed.searchParams.get("fact_type"), "project");
    assert.equal(parsed.searchParams.get("status"), "deprecated");
    assert.equal(parsed.searchParams.get("cursor"), "cursor/value+safe");
    assert.equal(result.totalActive, 12);
    assert.equal(result.nextCursor, "next/value+safe");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("loadContextFacts maps an unauthenticated response to an empty list", async () => {
  globalThis.fetch = (async () => jsonResponse({ error: "ログインが必要です。" }, 401)) as typeof fetch;

  try {
    const result = await loadContextFacts({ status: "active" });
    assert.deepEqual(result, { facts: [], totalActive: 0, nextCursor: null });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("loadContextFacts exposes the API error message", async () => {
  globalThis.fetch = (async () => jsonResponse({ error: "状態の指定が不正です。" }, 400)) as typeof fetch;

  try {
    await assert.rejects(
      () => loadContextFacts({ status: "active" }),
      /状態の指定が不正です。/,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});
