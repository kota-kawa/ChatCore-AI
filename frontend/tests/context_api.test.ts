import assert from "node:assert/strict";
import test from "node:test";

import {
  approveContextCandidate,
  loadContextCandidates,
  loadContextExtractionSettings,
  loadContextFacts,
  rejectContextCandidate,
  updateContextExtractionSettings,
} from "../lib/memo/context_api";

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

test("loadContextCandidates sends pending pagination parameters and maps totals", async () => {
  let requestedUrl = "";
  globalThis.fetch = (async (input) => {
    requestedUrl = String(input);
    return jsonResponse({ candidates: [], total_pending: 7, next_cursor: "candidate-next" });
  }) as typeof fetch;

  try {
    const result = await loadContextCandidates({
      status: "pending",
      limit: 20,
      cursor: "candidate/cursor+safe",
    });

    const parsed = new URL(requestedUrl, "https://example.com");
    assert.equal(parsed.pathname, "/api/context-facts/candidates");
    assert.equal(parsed.searchParams.get("status"), "pending");
    assert.equal(parsed.searchParams.get("limit"), "20");
    assert.equal(parsed.searchParams.get("cursor"), "candidate/cursor+safe");
    assert.equal(result.totalPending, 7);
    assert.equal(result.nextCursor, "candidate-next");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("candidate approval and rejection send revision-guarded PUT requests", async () => {
  const requests: { url: string; init?: RequestInit }[] = [];
  globalThis.fetch = (async (input, init) => {
    requests.push({ url: String(input), init });
    return jsonResponse({ status: "success" });
  }) as typeof fetch;

  try {
    await approveContextCandidate(12, {
      revision: 3,
      title: "編集済み",
      fact_type: "decision",
    });
    await rejectContextCandidate(13, { revision: 4 });

    assert.equal(requests[0]?.url, "/api/context-facts/candidates/12/approve");
    assert.equal(requests[0]?.init?.method, "PUT");
    assert.deepEqual(JSON.parse(String(requests[0]?.init?.body)), {
      revision: 3,
      title: "編集済み",
      fact_type: "decision",
    });
    assert.equal(requests[1]?.url, "/api/context-facts/candidates/13/reject");
    assert.equal(requests[1]?.init?.method, "PUT");
    assert.deepEqual(JSON.parse(String(requests[1]?.init?.body)), { revision: 4 });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("context extraction settings default to off and can be explicitly enabled", async () => {
  const requests: { url: string; init?: RequestInit }[] = [];
  globalThis.fetch = (async (input, init) => {
    requests.push({ url: String(input), init });
    if (init?.method === "PUT") return jsonResponse({ enabled: true });
    return jsonResponse({});
  }) as typeof fetch;

  try {
    assert.deepEqual(await loadContextExtractionSettings(), { enabled: false });
    assert.deepEqual(await updateContextExtractionSettings({ enabled: true }), { enabled: true });
    assert.equal(requests[0]?.url, "/api/context-facts/extraction-settings");
    assert.equal(requests[1]?.init?.method, "PUT");
    assert.deepEqual(JSON.parse(String(requests[1]?.init?.body)), { enabled: true });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("candidate APIs expose backend error messages", async () => {
  globalThis.fetch = (async () =>
    jsonResponse({ error: "候補のrevisionが競合しています。" }, 409)) as typeof fetch;

  try {
    await assert.rejects(
      () => approveContextCandidate(12, { revision: 1 }),
      /候補のrevisionが競合しています。/,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});
