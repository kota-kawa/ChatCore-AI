import assert from "node:assert/strict";
import test from "node:test";

import { sanitizeClassAttributeValue } from "../scripts/core/html";

test("sanitizeClassAttributeValue preserves web search source UI classes", () => {
  assert.equal(
    sanitizeClassAttributeValue(
      "web-search-sources web-search-sources--trace web-search-sources__summary web-search-sources__link unsafe-class"
    ),
    "web-search-sources web-search-sources--trace web-search-sources__summary web-search-sources__link"
  );
});

test("sanitizeClassAttributeValue preserves inline web search citation classes", () => {
  assert.equal(
    sanitizeClassAttributeValue(
      "web-search-citation web-search-citation__icon web-search-citation__icon--fallback web-search-citation__favicon web-search-citation__fallback web-search-citation__label unsafe-class",
    ),
    "web-search-citation web-search-citation__icon web-search-citation__icon--fallback web-search-citation__favicon web-search-citation__fallback web-search-citation__label",
  );
});

test("sanitizeClassAttributeValue preserves memo preview blank line spacer class", () => {
  assert.equal(
    sanitizeClassAttributeValue("memo-preserved-blank-line unsafe-class"),
    "memo-preserved-blank-line"
  );
});
