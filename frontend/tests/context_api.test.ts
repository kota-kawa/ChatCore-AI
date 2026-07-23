import assert from "node:assert/strict";
import test from "node:test";

import {
  approveContextCandidate,
  confirmContextVaultImport,
  createContextFact,
  exportContextVault,
  loadContextCandidates,
  loadContextExtractionSettings,
  loadContextFacts,
  previewContextVaultImport,
  rejectContextCandidate,
  updateContextFact,
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

test("loadContextFacts exposes an expired session and updates the shared auth cache", async () => {
  const storedValues = new Map<string, string>();
  const originalLocalStorage = globalThis.localStorage;
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    value: {
      getItem: (key: string) => storedValues.get(key) ?? null,
      setItem: (key: string, value: string) => storedValues.set(key, value),
    },
  });
  globalThis.fetch = (async () => jsonResponse({ error: "ログインが必要です。" }, 401)) as typeof fetch;

  try {
    await assert.rejects(
      () => loadContextFacts({ status: "active" }),
      (error: Error & { status?: number }) => {
        assert.match(error.message, /ログインセッションが切れました。再ログインしてください。/);
        assert.equal(error.status, 401);
        return true;
      },
    );
    assert.equal(storedValues.get("chatcore.auth.loggedIn"), "0");
    assert.ok(storedValues.has("chatcore.auth.cachedAt"));
  } finally {
    globalThis.fetch = originalFetch;
    Object.defineProperty(globalThis, "localStorage", {
      configurable: true,
      value: originalLocalStorage,
    });
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

test("createContextFact sends the POST payload and returns the created fact", async () => {
  const requests: { url: string; init?: RequestInit }[] = [];
  const createdFact = {
    id: 21,
    fact_type: "project" as const,
    title: "Chat-Core",
    content: "Context Vaultを実装する。",
    status: "active" as const,
    revision: 1,
    source_kind: "manual" as const,
    importance: 75,
    created_at: "2026-07-23T12:00:00Z",
    updated_at: "2026-07-23T12:00:00Z",
  };
  globalThis.fetch = (async (input, init) => {
    requests.push({ url: String(input), init });
    return jsonResponse({ status: "success", fact: createdFact });
  }) as typeof fetch;

  try {
    const input = {
      fact_type: "project" as const,
      title: "Chat-Core",
      content: "Context Vaultを実装する。",
      importance: 75,
    };
    const result = await createContextFact(input);

    assert.deepEqual(result, createdFact);
    assert.equal(requests[0]?.url, "/api/context-facts");
    assert.equal(requests[0]?.init?.method, "POST");
    assert.equal(new Headers(requests[0]?.init?.headers).get("Content-Type"), "application/json");
    assert.deepEqual(JSON.parse(String(requests[0]?.init?.body)), input);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("createContextFact exposes backend errors", async () => {
  globalThis.fetch = (async () =>
    jsonResponse({ error: "有効なコンテキストは200件までです。" }, 409)) as typeof fetch;

  try {
    await assert.rejects(
      () =>
        createContextFact({
          fact_type: "profile",
          title: "プロフィール",
          content: "サンプル",
          importance: 50,
        }),
      /有効なコンテキストは200件までです。/,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("updateContextFact sends the revision-guarded PUT payload and returns the updated fact", async () => {
  const requests: { url: string; init?: RequestInit }[] = [];
  const updatedFact = {
    id: 21,
    fact_type: "decision" as const,
    title: "権限分離",
    content: "メモとコンテキストの権限を分離する。",
    status: "deprecated" as const,
    revision: 4,
    source_kind: "manual" as const,
    importance: 75,
    created_at: "2026-07-23T12:00:00Z",
    updated_at: "2026-07-23T12:30:00Z",
  };
  globalThis.fetch = (async (input, init) => {
    requests.push({ url: String(input), init });
    return jsonResponse({ status: "success", fact: updatedFact });
  }) as typeof fetch;

  try {
    const input = {
      revision: 3,
      fact_type: "decision" as const,
      title: "権限分離",
      content: "メモとコンテキストの権限を分離する。",
      status: "deprecated" as const,
      importance: 75,
    };
    const result = await updateContextFact(21, input);

    assert.deepEqual(result, updatedFact);
    assert.equal(requests[0]?.url, "/api/context-facts/21");
    assert.equal(requests[0]?.init?.method, "PUT");
    assert.equal(new Headers(requests[0]?.init?.headers).get("Content-Type"), "application/json");
    assert.deepEqual(JSON.parse(String(requests[0]?.init?.body)), input);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("updateContextFact exposes revision conflict errors", async () => {
  globalThis.fetch = (async () =>
    jsonResponse({ error: "コンテキストが更新されています。再読み込みしてください。" }, 409)) as typeof fetch;

  try {
    await assert.rejects(
      () => updateContextFact(21, { revision: 3, status: "active" }),
      /コンテキストが更新されています。再読み込みしてください。/,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("exportContextVault requests the selected format and keeps the attachment filename", async () => {
  let requestedUrl = "";
  globalThis.fetch = (async (input) => {
    requestedUrl = String(input);
    return new Response('{"version":1}', {
      status: 200,
      headers: {
        "Content-Type": "application/json",
        "Content-Disposition": "attachment; filename*=UTF-8''my%20context.json",
      },
    });
  }) as typeof fetch;

  try {
    const result = await exportContextVault("json");
    const parsed = new URL(requestedUrl, "https://example.com");
    assert.equal(parsed.pathname, "/api/context-facts/export");
    assert.equal(parsed.searchParams.get("format"), "json");
    assert.equal(result.filename, "my context.json");
    assert.equal(await result.blob.text(), '{"version":1}');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("context import preview and confirmation send the reviewed content and preview token", async () => {
  const requests: { url: string; init?: RequestInit }[] = [];
  const preview = {
    preview_token: "signed-preview",
    total_count: 2,
    active_count: 1,
    deprecated_count: 1,
    duplicate_count: 0,
    importable_count: 2,
    can_import: true,
    sample_facts: [],
    warnings: [],
    expires_at: "2026-07-23T13:00:00Z",
  };
  const imported = {
    status: "success" as const,
    imported_count: 2,
    skipped_duplicate_count: 0,
    active_count: 1,
    deprecated_count: 1,
  };
  globalThis.fetch = (async (input, init) => {
    requests.push({ url: String(input), init });
    return jsonResponse(requests.length === 1 ? preview : imported);
  }) as typeof fetch;

  try {
    const content = '{"facts":[]}';
    assert.deepEqual(await previewContextVaultImport({ format: "json", content }), preview);
    assert.deepEqual(
      await confirmContextVaultImport({
        format: "json",
        content,
        preview_token: "signed-preview",
      }),
      imported,
    );
    assert.equal(requests[0]?.url, "/api/context-facts/import/preview");
    assert.equal(requests[0]?.init?.method, "POST");
    assert.deepEqual(JSON.parse(String(requests[0]?.init?.body)), { format: "json", content });
    assert.equal(requests[1]?.url, "/api/context-facts/import");
    assert.equal(requests[1]?.init?.method, "POST");
    assert.deepEqual(JSON.parse(String(requests[1]?.init?.body)), {
      format: "json",
      content,
      preview_token: "signed-preview",
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("context portability APIs expose backend validation errors", async () => {
  globalThis.fetch = (async () =>
    jsonResponse({ error: "インポートできる事実は1000件までです。" }, 400)) as typeof fetch;

  try {
    await assert.rejects(
      () => previewContextVaultImport({ format: "markdown", content: "# context" }),
      /インポートできる事実は1000件までです。/,
    );
    await assert.rejects(
      () => exportContextVault("markdown"),
      /インポートできる事実は1000件までです。/,
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
