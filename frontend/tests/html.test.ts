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

test("sanitizeClassAttributeValue preserves selected-reference citation classes", () => {
  assert.equal(
    sanitizeClassAttributeValue(
      "selected-reference-citation selected-reference-citation--personal unsafe-class",
    ),
    "selected-reference-citation selected-reference-citation--personal",
  );
});

test("sanitizeClassAttributeValue preserves memo preview blank line spacer class", () => {
  assert.equal(
    sanitizeClassAttributeValue("memo-preserved-blank-line unsafe-class"),
    "memo-preserved-blank-line"
  );
});

test("sanitizeClassAttributeValue preserves copy card classes", () => {
  assert.equal(
    sanitizeClassAttributeValue(
      "copy-block-container copy-block-header copy-block-label copy-block-copy-btn copy-block-text unsafe-class",
    ),
    "copy-block-container copy-block-header copy-block-label copy-block-copy-btn copy-block-text",
  );
});
