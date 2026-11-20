// 個人コンテキストAPIのフィルター・カーソル・認証失効・自動抽出の設定を検証する。
// Tests context api behavior.

import assert from "node:assert/strict";
import test from "node:test";

import {
  confirmContextVaultImport,
  createContextFact,
  deleteAllContextFacts,
  deleteContextFact,
  exportContextVault,
  loadContextExtractionSettings,
  loadContextFacts,
  loadContextMemoryUseSettings,
  previewContextVaultImport,
  revertContextFactReplacement,
  updateContextFact,
  updateContextExtractionSettings,
  updateContextMemoryUseSettings,
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

test("loadContextFacts sends the trimmed search query as q and omits an empty one", async () => {
  const requestedUrls: string[] = [];
  globalThis.fetch = (async (input) => {
    requestedUrls.push(String(input));
    return jsonResponse({ facts: [], total_active: 0, next_cursor: null });
  }) as typeof fetch;

  try {
    await loadContextFacts({ status: "active", query: "  東京 100%_  " });
    await loadContextFacts({ status: "active", query: "   " });
    await loadContextFacts({ status: "active", query: null });
    await loadContextFacts({ status: "deprecated", factType: "profile", cursor: "c1", query: "住所" });
    await loadContextFacts({ status: "active", query: " 、。 ,; " });

    const [searched, blank, none, combined, punctuationOnly] = requestedUrls.map((url) => new URL(url, "https://example.com").searchParams);
    // 記号は URL エンコードされて 1 つの値として届く（クエリの区切りや LIKE の記号をここで加工しない）。
    // Symbols are URL-encoded into one value (the client does not touch query separators or LIKE symbols).
    assert.equal(searched?.get("q"), "東京 100%_");
    assert.equal(blank?.has("q"), false);
    assert.equal(none?.has("q"), false);
    // 語が 1 つも残らない検索語はサーバーが「検索なし」として扱うので、送らない。
    // A query that leaves no term is "no search" to the server, so it is not sent.
    assert.equal(punctuationOnly?.has("q"), false);
    assert.deepEqual(
      [combined?.get("q"), combined?.get("status"), combined?.get("fact_type"), combined?.get("cursor")],
      ["住所", "deprecated", "profile", "c1"],
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("loadContextFacts fills source and replacement defaults for a response from an older server", async () => {
  globalThis.fetch = (async () =>
    jsonResponse({
      facts: [
        { id: 1, fact_type: "profile", title: "旧応答", content: "x", status: "active", revision: 1, source_kind: "chat", importance: 50 },
        {
          id: 2,
          fact_type: "profile",
          title: "新応答",
          content: "y",
          status: "active",
          revision: 1,
          source_kind: "chat",
          importance: 50,
          source_count: 4,
          last_mentioned_at: "2026-11-01T00:00:00+00:00",
          sources: [{ chat_room_id: "room-1", evidence: "引用", observed_at: "2026-11-01T00:00:00+00:00" }],
          replaces: { id: 9, title: "旧", content: "古い内容" },
        },
      ],
      total_active: 2,
      next_cursor: null,
    })) as typeof fetch;

  try {
    const { facts } = await loadContextFacts({ status: "active" });
    assert.deepEqual(
      [facts[0]?.source_count, facts[0]?.last_mentioned_at, facts[0]?.sources, facts[0]?.superseded_by, facts[0]?.replaces],
      [0, null, [], null, null],
    );
    assert.equal(facts[1]?.source_count, 4);
    assert.equal(facts[1]?.sources?.[0]?.chat_room_id, "room-1");
    assert.equal(facts[1]?.replaces?.content, "古い内容");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("revertContextFactReplacement POSTs the new memory's revision and returns both facts", async () => {
  const requests: { url: string; init?: RequestInit }[] = [];
  const fact = { id: 4, status: "deprecated", revision: 3 };
  const restored = { id: 3, status: "active", revision: 6 };
  globalThis.fetch = (async (input, init) => {
    requests.push({ url: String(input), init });
    return jsonResponse({ status: "success", fact, restored_fact: restored });
  }) as typeof fetch;

  try {
    const result = await revertContextFactReplacement(4, 2);
    assert.equal(requests[0]?.url, "/api/context-facts/4/revert-replacement");
    assert.equal(requests[0]?.init?.method, "POST");
    assert.deepEqual(JSON.parse(String(requests[0]?.init?.body)), { revision: 2 });
    assert.deepEqual([result.fact.id, result.restored_fact.id], [4, 3]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("revertContextFactReplacement exposes a conflict and treats a body without both facts as a failure", async () => {
  globalThis.fetch = (async () => jsonResponse({ error: "この置き換えは元に戻せません。" }, 409)) as typeof fetch;
  try {
    await assert.rejects(() => revertContextFactReplacement(4, 2), /この置き換えは元に戻せません。/);
  } finally {
    globalThis.fetch = originalFetch;
  }

  globalThis.fetch = (async () => jsonResponse({ status: "success" })) as typeof fetch;
  try {
    await assert.rejects(() => revertContextFactReplacement(4, 2));
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("deleteContextFact sends DELETE with the revision in the query", async () => {
  const requests: { url: string; init?: RequestInit }[] = [];
  globalThis.fetch = (async (input, init) => {
    requests.push({ url: String(input), init });
    return jsonResponse({ status: "success" });
  }) as typeof fetch;

  try {
    await deleteContextFact(21, 7);
    assert.equal(requests[0]?.url, "/api/context-facts/21?revision=7");
    assert.equal(requests[0]?.init?.method, "DELETE");
  } finally {
    globalThis.fetch = originalFetch;
  }

  globalThis.fetch = (async () => jsonResponse({ error: "他の場所で先に更新されました。" }, 409)) as typeof fetch;
  try {
    await assert.rejects(() => deleteContextFact(21, 7), /他の場所で先に更新されました。/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("deleteAllContextFacts sends the confirmation value and returns the deleted count", async () => {
  const requests: { url: string; init?: RequestInit }[] = [];
  globalThis.fetch = (async (input, init) => {
    requests.push({ url: String(input), init });
    return jsonResponse({ status: "success", deleted_count: 12 });
  }) as typeof fetch;

  try {
    assert.equal(await deleteAllContextFacts(), 12);
    assert.equal(requests[0]?.url, "/api/context-facts?confirm=delete-all");
    assert.equal(requests[0]?.init?.method, "DELETE");
  } finally {
    globalThis.fetch = originalFetch;
  }

  globalThis.fetch = (async () => jsonResponse({ status: "success" })) as typeof fetch;
  try {
    assert.equal(await deleteAllContextFacts(), 0);
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

test("memory use settings use their own endpoint, default to off and can be switched", async () => {
  const requests: { url: string; init?: RequestInit }[] = [];
  globalThis.fetch = (async (input, init) => {
    requests.push({ url: String(input), init });
    if (init?.method === "PUT") return jsonResponse({ status: "success", enabled: false });
    return jsonResponse({});
  }) as typeof fetch;

  try {
    assert.deepEqual(await loadContextMemoryUseSettings(), { enabled: false });
    assert.deepEqual(await updateContextMemoryUseSettings({ enabled: false }), { enabled: false });
    assert.equal(requests[0]?.url, "/api/context-facts/memory-use-settings");
    assert.equal(requests[1]?.url, "/api/context-facts/memory-use-settings");
    assert.equal(requests[1]?.init?.method, "PUT");
    assert.deepEqual(JSON.parse(String(requests[1]?.init?.body)), { enabled: false });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("a signed-out session reads the memory use setting as off and a server error is reported", async () => {
  globalThis.fetch = (async () => jsonResponse({ error: "ログインしてください。" }, 401)) as typeof fetch;
  try {
    assert.deepEqual(await loadContextMemoryUseSettings(), { enabled: false });
  } finally {
    globalThis.fetch = originalFetch;
  }

  globalThis.fetch = (async () => jsonResponse({ error: "サーバーエラー" }, 500)) as typeof fetch;
  try {
    await assert.rejects(() => loadContextMemoryUseSettings(), /サーバーエラー/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
