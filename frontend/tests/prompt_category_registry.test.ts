import assert from "node:assert/strict";
import test from "node:test";

import {
  CATEGORY_OTHER,
  CATEGORY_UNSET,
  PROMPT_CATEGORY_KEYS,
  PROMPT_CATEGORY_REGISTRY,
  getCategoryLabel,
  getCategoryLabelOrFallback,
  normalizeCategory
} from "../scripts/prompt_share/prompt_category_registry";

test("canonical keys normalize to themselves and resolve to a label", () => {
  for (const category of PROMPT_CATEGORY_REGISTRY) {
    assert.equal(normalizeCategory(category.key), category.key);
    assert.equal(getCategoryLabel(category.key), category.label);
  }
});

test("legacy Japanese categories resolve to canonical keys", () => {
  assert.equal(normalizeCategory("仕事"), "business");
  assert.equal(normalizeCategory("恋愛"), "daily_life");
  assert.equal(normalizeCategory("旅行"), "daily_life");
  assert.equal(normalizeCategory("スポーツ"), "hobby");
  assert.equal(normalizeCategory("勉強"), "learning");
  assert.equal(normalizeCategory("その他"), CATEGORY_OTHER);
  assert.equal(normalizeCategory("未選択"), CATEGORY_UNSET);
});

test("empty is unset and unknown values are rejected", () => {
  assert.equal(normalizeCategory(""), CATEGORY_UNSET);
  assert.equal(normalizeCategory("   "), CATEGORY_UNSET);
  assert.equal(normalizeCategory(undefined), CATEGORY_UNSET);
  assert.equal(normalizeCategory("架空のカテゴリ"), null);
});

test("display fallback covers unset and unknown categories", () => {
  assert.equal(getCategoryLabelOrFallback("business"), "仕事・ビジネス");
  assert.equal(getCategoryLabelOrFallback(""), "未分類");
  assert.equal(getCategoryLabelOrFallback("架空のカテゴリ"), "未分類");
});

test("the catch-all category stays last so the filter UI reads naturally", () => {
  assert.equal(PROMPT_CATEGORY_KEYS.at(-1), CATEGORY_OTHER);
});
