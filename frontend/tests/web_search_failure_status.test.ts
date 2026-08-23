import assert from "node:assert/strict";
import test from "node:test";

import { getWebSearchFailureStatus } from "../lib/chat_page/web_search_failure_status";

test("maps stable web-search error codes without inspecting localized messages", () => {
  assert.equal(getWebSearchFailureStatus("web_search.configuration"), "configuration");
  assert.equal(getWebSearchFailureStatus("web_search.quota_exceeded"), "quota_exceeded");
  assert.equal(getWebSearchFailureStatus("web_search.request_failed"), "request_failed");
});

test("uses the generic status for missing, unknown, or message-shaped values", () => {
  assert.equal(getWebSearchFailureStatus(undefined), "request_failed");
  assert.equal(getWebSearchFailureStatus("APIキーがありません"), "request_failed");
  assert.equal(getWebSearchFailureStatus({ code: "web_search.quota_exceeded" }), "request_failed");
});
