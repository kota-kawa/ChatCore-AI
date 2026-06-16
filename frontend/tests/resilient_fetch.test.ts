import assert from "node:assert/strict";
import test from "node:test";

import { resilientFetch } from "../scripts/core/resilient_fetch";

const originalFetch = globalThis.fetch;

function makeResponse(status: number): Response {
  return new Response(JSON.stringify({ ok: status < 400 }), {
    status,
    headers: { "content-type": "application/json" },
  });
}

// signal の中断時に AbortError で reject する fetch をシミュレートする。
// Simulates a fetch that rejects with AbortError when its signal aborts.
function hangingFetch(): typeof fetch {
  return ((_input: RequestInfo | URL, init?: RequestInit) =>
    new Promise<Response>((_resolve, reject) => {
      const signal = init?.signal;
      if (signal?.aborted) {
        reject(new DOMException("Aborted", "AbortError"));
        return;
      }
      signal?.addEventListener(
        "abort",
        () => reject(new DOMException("Aborted", "AbortError")),
        { once: true },
      );
    })) as typeof fetch;
}

function restoreFetch() {
  globalThis.fetch = originalFetch;
}

const fastRetry = { retryBaseDelayMs: 1, retryMaxDelayMs: 2 } as const;

test("returns the response without retrying on success", async () => {
  let calls = 0;
  globalThis.fetch = (async () => {
    calls += 1;
    return makeResponse(200);
  }) as typeof fetch;

  try {
    const response = await resilientFetch("/api/test", undefined, fastRetry);
    assert.equal(response.status, 200);
    assert.equal(calls, 1);
  } finally {
    restoreFetch();
  }
});

test("retries on 5xx and then succeeds", async () => {
  let calls = 0;
  globalThis.fetch = (async () => {
    calls += 1;
    return makeResponse(calls < 3 ? 503 : 200);
  }) as typeof fetch;

  try {
    const response = await resilientFetch("/api/test", undefined, { retries: 3, ...fastRetry });
    assert.equal(response.status, 200);
    assert.equal(calls, 3);
  } finally {
    restoreFetch();
  }
});

test("does not retry on 4xx", async () => {
  let calls = 0;
  globalThis.fetch = (async () => {
    calls += 1;
    return makeResponse(404);
  }) as typeof fetch;

  try {
    const response = await resilientFetch("/api/test", undefined, { retries: 3, ...fastRetry });
    assert.equal(response.status, 404);
    assert.equal(calls, 1);
  } finally {
    restoreFetch();
  }
});

test("retries on network error and then succeeds", async () => {
  let calls = 0;
  globalThis.fetch = (async () => {
    calls += 1;
    if (calls < 2) throw new TypeError("Failed to fetch");
    return makeResponse(200);
  }) as typeof fetch;

  try {
    const response = await resilientFetch("/api/test", undefined, { retries: 3, ...fastRetry });
    assert.equal(response.status, 200);
    assert.equal(calls, 2);
  } finally {
    restoreFetch();
  }
});

test("does not retry non-idempotent POST requests", async () => {
  let calls = 0;
  globalThis.fetch = (async () => {
    calls += 1;
    return makeResponse(503);
  }) as typeof fetch;

  try {
    const response = await resilientFetch("/api/test", { method: "POST" }, { retries: 3, ...fastRetry });
    assert.equal(response.status, 503);
    assert.equal(calls, 1);
  } finally {
    restoreFetch();
  }
});

test("aborts a hanging request after the timeout", async () => {
  globalThis.fetch = hangingFetch();
  try {
    await assert.rejects(
      resilientFetch("/api/test", undefined, { timeoutMs: 10, retries: 0 }),
    );
  } finally {
    restoreFetch();
  }
});

test("propagates a caller abort without issuing a request", async () => {
  let calls = 0;
  globalThis.fetch = (async () => {
    calls += 1;
    return makeResponse(200);
  }) as typeof fetch;

  const controller = new AbortController();
  controller.abort();

  try {
    await assert.rejects(
      resilientFetch("/api/test", { signal: controller.signal }, fastRetry),
      (error: unknown) => (error as { name?: string })?.name === "AbortError",
    );
    assert.equal(calls, 0);
  } finally {
    restoreFetch();
  }
});
