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

// バグ3: fetch はヘッダー到達で解決するため、本文の読み取りはタイムアウトの
// 外に出やすい。ヘッダーだけ返して本文で止まるサーバーを模し、タイムアウトが
// 本文読み取り中も効き続けることを確認する。
// Bug 3: fetch settles as soon as headers arrive, so body reads can fall
// outside the timeout. Simulate a server that returns headers and then
// stalls, and verify the timeout still fires while the body is being read.
test("keeps the deadline armed while the body is read, not just until headers arrive", async () => {
  globalThis.fetch = (async (_input, init) => {
    const body = new ReadableStream<Uint8Array>({
      pull() {
        // 本文は永遠に届かない。中断シグナルでのみ失敗する（実際の fetch 実装が
        // AbortSignal を本文読み取りにも伝播させる契約を模している）。
        // The body never arrives; it only fails via the abort signal (mirroring
        // how a real fetch implementation propagates the AbortSignal into body reads).
        return new Promise<void>((_resolve, reject) => {
          init?.signal?.addEventListener(
            "abort",
            () => reject(new DOMException("Aborted", "AbortError")),
            { once: true },
          );
        });
      },
    });
    return new Response(body, { status: 200 });
  }) as typeof fetch;

  try {
    const response = await resilientFetch("/api/test", undefined, { timeoutMs: 10, retries: 0 });
    assert.equal(response.status, 200);
    // ヘッダーは届いたので resilientFetch 自体は成功する。タイムアウトが本文読み取りにも
    // 効いていれば、この本文読み取りは無限に待たずに失敗する。
    // Headers arrived, so resilientFetch itself succeeds. If the timeout still guards
    // the body read, this read fails instead of hanging forever.
    await assert.rejects(response.text());
  } finally {
    restoreFetch();
  }
});

test("still returns the full body for a normal response after wrapping it with the deadline", async () => {
  globalThis.fetch = (async () => makeResponse(200)) as typeof fetch;

  try {
    const response = await resilientFetch("/api/test", undefined, { timeoutMs: 50, retries: 0 });
    const payload = await response.json();
    assert.deepEqual(payload, { ok: true });
  } finally {
    restoreFetch();
  }
});

// SSE のように意図的に長時間開いたままにする経路は timeoutMs: 0 で呼び出す
// (frontend/hooks/chat_page/use_home_page_generation_actions.ts,
// frontend/components/chat_page/MiniChat.tsx を参照)。この場合は本文の読み取りが
// 長引いても打ち切ってはいけない。
// Long-lived, intentionally open connections like SSE call this with
// timeoutMs: 0 (see use_home_page_generation_actions.ts and MiniChat.tsx). In
// that mode a slow body read must never be cut off.
test("timeoutMs 0 never cuts off a slow body (SSE-style long-lived reads)", async () => {
  globalThis.fetch = (async () => {
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode("chunk-1"));
        setTimeout(() => {
          controller.enqueue(encoder.encode("chunk-2"));
          controller.close();
        }, 30);
      },
    });
    return new Response(body, { status: 200 });
  }) as typeof fetch;

  try {
    const response = await resilientFetch("/api/test", undefined, { timeoutMs: 0, retries: 0 });
    const text = await response.text();
    assert.equal(text, "chunk-1chunk-2");
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
