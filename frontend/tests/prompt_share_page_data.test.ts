import assert from "node:assert/strict";
import test from "node:test";

import { getPromptShareServerSideProps } from "../components/prompt_share/prompt_share_page_data";

const originalFetch = globalThis.fetch;

test("prompt share SSR requests only the first page and preserves its cursor", async () => {
  let requestedUrl = "";
  globalThis.fetch = (async (input) => {
    requestedUrl = String(input);
    return new Response(JSON.stringify({
      prompts: [{ id: 1, title: "Prompt", content: "Body" }],
      pagination: { limit: 24, has_next: true, next_cursor: "next-page" }
    }), {
      status: 200,
      headers: { "content-type": "application/json" }
    });
  }) as typeof fetch;

  try {
    const result = await getPromptShareServerSideProps({} as Parameters<typeof getPromptShareServerSideProps>[0]);
    assert.ok("props" in result);
    const props = await result.props;

    assert.match(requestedUrl, /\/prompt_share\/api\/prompts\?limit=24$/);
    assert.equal(props.initialPrompts?.length, 1);
    assert.equal(props.initialPagination?.has_next, true);
    assert.equal(props.initialPagination?.next_cursor, "next-page");
  } finally {
    globalThis.fetch = originalFetch;
  }
});
