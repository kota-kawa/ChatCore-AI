import assert from "node:assert/strict";
import test from "node:test";

import { buildPromptPath, buildPromptSlug, MAX_PROMPT_SLUG_LENGTH } from "../lib/promptSlug";

test("buildPromptSlug normalizes ASCII titles into hyphenated slugs", () => {
  assert.equal(buildPromptSlug("Blog Post Generator"), "blog-post-generator");
  assert.equal(buildPromptSlug("  Multiple   Spaces  "), "multiple-spaces");
  assert.equal(buildPromptSlug("Title: With/Punctuation!"), "title-with-punctuation");
});

test("buildPromptSlug keeps Japanese characters", () => {
  assert.equal(buildPromptSlug("ブログ記事 生成プロンプト"), "ブログ記事-生成プロンプト");
});

test("buildPromptSlug returns empty string for empty or symbol-only titles", () => {
  assert.equal(buildPromptSlug(""), "");
  assert.equal(buildPromptSlug(null), "");
  assert.equal(buildPromptSlug(undefined), "");
  assert.equal(buildPromptSlug("///###"), "");
});

test("buildPromptSlug caps the slug length and trims a trailing hyphen", () => {
  const longTitle = "a ".repeat(200).trim();
  const slug = buildPromptSlug(longTitle);
  assert.ok(slug.length <= MAX_PROMPT_SLUG_LENGTH);
  assert.doesNotMatch(slug, /-$/);
});

test("buildPromptPath appends the encoded slug to the ID path", () => {
  assert.equal(buildPromptPath(42, "Blog Post Generator"), "/shared/prompt/42/blog-post-generator");
  assert.equal(
    buildPromptPath("7", "ブログ記事"),
    `/shared/prompt/7/${encodeURIComponent("ブログ記事")}`
  );
});

test("buildPromptPath falls back to the ID-only path without a usable slug", () => {
  assert.equal(buildPromptPath(99), "/shared/prompt/99");
  assert.equal(buildPromptPath(99, "###"), "/shared/prompt/99");
});
