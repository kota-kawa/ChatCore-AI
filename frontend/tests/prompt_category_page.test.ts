import assert from "node:assert/strict";
import test from "node:test";

import { buildPromptCategoryStructuredData } from "../components/prompt_share/prompt_category_page";
import {
  getPromptCategoryPath,
  getPromptCategorySeoCopy,
  isPromptCategoryKey
} from "../components/prompt_share/prompt_category_seo";
import {
  PROMPT_CATEGORY_KEYS
} from "../scripts/prompt_share/prompt_category_registry";
import {
  fetchInitialPromptData,
  getPromptCategoryServerSideProps,
  getPromptShareServerSideProps
} from "../components/prompt_share/prompt_share_page_data";

const originalFetch = globalThis.fetch;

test("category SEO copy covers every registered category in both locales", () => {
  for (const category of PROMPT_CATEGORY_KEYS) {
    assert.equal(isPromptCategoryKey(category), true);
    for (const locale of ["ja", "en"] as const) {
      const copy = getPromptCategorySeoCopy(category, locale);
      assert.ok(copy);
      assert.ok(copy.title.length > 0);
      assert.ok(copy.description.length > 0);
      assert.ok(copy.intro.length > 0);
      assert.equal(copy.examples.length, 3);
      assert.ok(copy.tip.length > 0);
      assert.equal(getPromptCategorySeoCopy(category, locale)?.title, copy.title);
    }
  }
});

test("category paths keep Japanese public URLs and add /en for English", () => {
  assert.equal(getPromptCategoryPath("coding", "ja"), "/prompt_share/category/coding");
  assert.equal(getPromptCategoryPath("coding", "en"), "/en/prompt_share/category/coding");
});

test("category SSR requests the selected public category and normalizes prompts", async () => {
  let requestedUrl = "";
  let requestedHeaders: HeadersInit | undefined;
  globalThis.fetch = (async (input, init) => {
    requestedUrl = String(input);
    requestedHeaders = init?.headers;
    return new Response(JSON.stringify({
      prompts: [{ id: 8, title: "Review code", content: "**Body**", category: "coding" }],
      pagination: { limit: 24, has_next: false, next_cursor: null }
    }), { status: 200, headers: { "content-type": "application/json" } });
  }) as typeof fetch;

  try {
    const result = await getPromptCategoryServerSideProps({
      params: { category: "coding" },
      query: {},
      locale: "en",
      req: { headers: {} }
    } as never);
    assert.ok("props" in result);
    const props = await result.props;
    assert.match(requestedUrl, /\/prompt_share\/api\/prompts\?limit=24&category=coding$/);
    assert.equal(new Headers(requestedHeaders).get("accept-language"), "en");
    assert.equal(props.category, "coding");
    assert.equal(props.initialPrompts[0].content_format, "prompt");
    assert.equal(props.initialLoadFailed, false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("non-canonical category SSR returns notFound without contacting the API", async () => {
  let called = false;
  globalThis.fetch = (async () => {
    called = true;
    return new Response("{}", { status: 200 });
  }) as typeof fetch;

  try {
    const result = await getPromptCategoryServerSideProps({
      params: { category: "旅行" },
      query: {},
      req: { headers: {} }
    } as never);
    assert.deepEqual(result, { notFound: true });
    assert.equal(called, false);

    const uppercaseResult = await getPromptCategoryServerSideProps({
      params: { category: "CODING" },
      query: {},
      req: { headers: {} }
    } as never);
    assert.deepEqual(uppercaseResult, { notFound: true });
    assert.equal(called, false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("category SSR preserves an empty result and distinguishes API failures", async () => {
  globalThis.fetch = (async () => new Response(JSON.stringify({ prompts: [], pagination: { has_next: false } }), {
    status: 200,
    headers: { "content-type": "application/json" }
  })) as typeof fetch;
  try {
    const empty = await fetchInitialPromptData("writing");
    assert.equal(empty.initialPrompts.length, 0);
    assert.equal(empty.initialLoadFailed, false);

    globalThis.fetch = (async () => new Response("unavailable", { status: 503 })) as typeof fetch;
    const failed = await fetchInitialPromptData("writing");
    assert.equal(failed.initialPrompts.length, 0);
    assert.equal(failed.initialLoadFailed, true);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("main prompt share SSR uses a category query when it is a known key", async () => {
  let requestedUrl = "";
  globalThis.fetch = (async (input) => {
    requestedUrl = String(input);
    return new Response(JSON.stringify({ prompts: [], pagination: { has_next: false } }), {
      status: 200,
      headers: { "content-type": "application/json" }
    });
  }) as typeof fetch;
  try {
    const result = await getPromptShareServerSideProps({
      query: { category: "research" },
      req: { headers: {} }
    } as never);
    assert.ok("props" in result);
    const props = await result.props;
    assert.match(requestedUrl, /category=research$/);
    assert.equal(props.initialCategory, "research");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("category structured data exposes a localized collection and prompt item links", () => {
  const copy = getPromptCategorySeoCopy("coding", "en");
  assert.ok(copy);
  const structuredData = buildPromptCategoryStructuredData("coding", "en", copy, [
    { id: 42, title: "Code review", content: "Review this", category: "coding" }
  ]);
  const collection = structuredData.find((entry) => entry["@type"] === "CollectionPage") as {
    url: string;
    mainEntity: { itemListElement: Array<{ url: string; position: number }> };
  };
  assert.equal(collection.url, "/en/prompt_share/category/coding");
  assert.deepEqual(collection.mainEntity.itemListElement, [{
    "@type": "ListItem",
    position: 1,
    name: "Code review",
    url: "/en/shared/prompt/42/code-review"
  }]);
});
