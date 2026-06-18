import assert from "node:assert/strict";
import test from "node:test";

import { swrFetcher, HttpError } from "../lib/data/swr_fetcher";

const originalFetch = globalThis.fetch;

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function restore() {
  globalThis.fetch = originalFetch;
}

test("parses a JSON body on success", async () => {
  globalThis.fetch = (async () => jsonResponse({ hello: "world" })) as typeof fetch;
  try {
    const data = await swrFetcher<{ hello: string }>("/api/test");
    assert.equal(data.hello, "world");
  } finally {
    restore();
  }
});

test("throws an HttpError carrying the status and parsed info on failure", async () => {
  globalThis.fetch = (async () => jsonResponse({ message: "nope" }, 403)) as typeof fetch;
  try {
    await assert.rejects(
      () => swrFetcher("/api/test"),
      (error: unknown) => {
        assert.ok(error instanceof HttpError);
        assert.equal(error.status, 403);
        assert.equal(error.message, "nope");
        assert.deepEqual(error.info, { message: "nope" });
        return true;
      },
    );
  } finally {
    restore();
  }
});

test("falls back to text when the body is not JSON", async () => {
  globalThis.fetch = (async () =>
    new Response("plain text", { status: 200, headers: { "content-type": "text/plain" } })) as typeof fetch;
  try {
    const data = await swrFetcher<string>("/api/test");
    assert.equal(data, "plain text");
  } finally {
    restore();
  }
});

test("uses a default message when an error body has no message", async () => {
  globalThis.fetch = (async () =>
    new Response("", { status: 500 })) as typeof fetch;
  try {
    await assert.rejects(
      () => swrFetcher("/api/test", { resilient: { retries: 0 } }),
      (error: unknown) => {
        assert.ok(error instanceof HttpError);
        assert.equal(error.status, 500);
        assert.match(error.message, /status 500/);
        return true;
      },
    );
  } finally {
    restore();
  }
});
