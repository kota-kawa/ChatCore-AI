import assert from "node:assert/strict";
import test from "node:test";

import { loadMemoList } from "../lib/memo/api";
import { DEFAULT_LIMIT, MAX_MEMO_LIST_REQUEST_LIMIT } from "../lib/memo/constants";
import type { MemoSummary } from "../lib/memo/types";
import { buildMemoListUrl } from "../lib/memo/utils";

const baseOptions = { query: "", sort: "manual", archiveScope: "active", collectionId: null };

function paramsOf(url: string) {
  return new URLSearchParams(url.split("?")[1] ?? "");
}

test("buildMemoListUrl falls back to the default limit", () => {
  const params = paramsOf(buildMemoListUrl(baseOptions));

  assert.equal(params.get("limit"), String(DEFAULT_LIMIT));
  assert.equal(params.get("offset"), "0");
});

test("buildMemoListUrl reflects the requested limit", () => {
  const params = paramsOf(buildMemoListUrl({ ...baseOptions, limit: DEFAULT_LIMIT * 3 }));

  assert.equal(params.get("limit"), String(DEFAULT_LIMIT * 3));
  assert.equal(params.get("offset"), "0");
});

test("buildMemoListUrl keeps the filters while the limit grows", () => {
  const params = paramsOf(
    buildMemoListUrl({ query: "  design  ", sort: "recent", archiveScope: "archived", collectionId: 7, limit: 200 }),
  );

  assert.equal(params.get("limit"), "200");
  assert.equal(params.get("q"), "design");
  assert.equal(params.get("sort"), "recent");
  assert.equal(params.get("only_archived"), "1");
  assert.equal(params.get("collection_id"), "7");
});

// ---------------------------------------------------------------------------
// loadMemoList: the backend caps one request at MAX_MEMO_LIST_REQUEST_LIMIT rows
// ---------------------------------------------------------------------------

function makeMemos(from: number, count: number): MemoSummary[] {
  return Array.from({ length: count }, (_, index) => ({ id: from + index }));
}

function stubFetch(total: number) {
  const requested: string[] = [];
  const original = globalThis.fetch;
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const url = String(input);
    requested.push(url);
    const params = paramsOf(url);
    const limit = Number(params.get("limit"));
    const offset = Number(params.get("offset"));
    const memos = makeMemos(offset + 1, Math.max(0, Math.min(limit, total - offset)));
    return { ok: true, status: 200, json: async () => ({ memos, total }) } as unknown as Response;
  }) as typeof globalThis.fetch;
  return {
    requested,
    restore() {
      globalThis.fetch = original;
    },
  };
}

test("loadMemoList splits a limit above the per-request cap into offset-shifted requests", async () => {
  const total = 150;
  const stub = stubFetch(total);
  try {
    const result = await loadMemoList(buildMemoListUrl({ ...baseOptions, limit: 150 }));

    assert.equal(result.total, total);
    assert.equal(result.memos.length, 150);
    assert.deepEqual(
      result.memos.map((memo) => memo.id),
      makeMemos(1, 150).map((memo) => memo.id),
    );
    assert.equal(stub.requested.length, 2);
    assert.equal(paramsOf(stub.requested[0]).get("limit"), String(MAX_MEMO_LIST_REQUEST_LIMIT));
    assert.equal(paramsOf(stub.requested[0]).get("offset"), "0");
    assert.equal(paramsOf(stub.requested[1]).get("limit"), "50");
    assert.equal(paramsOf(stub.requested[1]).get("offset"), String(MAX_MEMO_LIST_REQUEST_LIMIT));
  } finally {
    stub.restore();
  }
});

test("loadMemoList issues a single request while the limit fits in one page", async () => {
  const stub = stubFetch(200);
  try {
    const result = await loadMemoList(buildMemoListUrl(baseOptions));

    assert.equal(result.memos.length, DEFAULT_LIMIT);
    assert.equal(stub.requested.length, 1);
  } finally {
    stub.restore();
  }
});

test("loadMemoList stops once the server runs out of rows", async () => {
  const stub = stubFetch(120);
  try {
    const result = await loadMemoList(buildMemoListUrl({ ...baseOptions, limit: 200 }));

    assert.equal(result.memos.length, 120);
    assert.equal(result.total, 120);
    assert.equal(stub.requested.length, 2);
  } finally {
    stub.restore();
  }
});
