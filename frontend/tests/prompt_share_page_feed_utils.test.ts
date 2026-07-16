import assert from "node:assert/strict";
import test from "node:test";

import {
  appendUniquePromptRecords,
  buildInitialPromptRecords,
  buildPromptCountMeta,
  filterPrompts,
  getFilterEmptyMessage,
  toCachedPromptData,
} from "../components/prompt_share/prompt_share_page_feed_utils";
import type { PromptRecord } from "../components/prompt_share/prompt_card";

const prompts: PromptRecord[] = [
  {
    id: 1,
    title: "メール文面",
    category: "writing",
    content: "Write an email",
    content_format: "prompt",
    media_type: "text",
    clientId: "prompt-1",
    liked: false,
    used_in_chat: false,
  },
  {
    id: 2,
    title: "画像生成",
    category: "creative",
    content: "Create an image",
    content_format: "prompt",
    media_type: "image",
    clientId: "prompt-2",
    liked: false,
    used_in_chat: false,
  },
  {
    id: 3,
    title: "SKILL",
    category: "coding",
    content: "",
    content_format: "skill",
    media_type: "text",
    clientId: "prompt-3",
    liked: false,
    used_in_chat: false,
  },
];

test("filterPrompts applies category, format, and media filters together", () => {
  assert.deepEqual(
    filterPrompts(prompts, "creative", "prompt", "image").map((prompt) => prompt.id),
    [2],
  );
  assert.deepEqual(
    filterPrompts(prompts, "all", "skill", "all").map((prompt) => prompt.id),
    [3],
  );
});

test("buildPromptCountMeta preserves category and search count labels", () => {
  assert.equal(
    buildPromptCountMeta(prompts, "all", "all", "all"),
    "公開プロンプト: 3件",
  );
  // カテゴリキーはカウントラベルでも表示ラベルへ解決される
  // The category key is resolved to its display label in the count meta too
  assert.equal(
    buildPromptCountMeta(prompts, "coding", "all", "all"),
    "開発・プログラミング: 1件",
  );
  assert.equal(
    buildPromptCountMeta(prompts, null, "prompt", "image", { searchTotal: 8 }),
    "検索結果 / プロンプト / 画像: 1件 / 8件",
  );
});

test("getFilterEmptyMessage includes active axis labels", () => {
  assert.equal(
    getFilterEmptyMessage("all", "all"),
    "条件に一致するプロンプトが見つかりませんでした。",
  );
  assert.equal(
    getFilterEmptyMessage("skill", "text"),
    "SKILL / テキストのプロンプトが見つかりませんでした。",
  );
});

test("initial records and cache data keep client-only fields separated", () => {
  const records = buildInitialPromptRecords([
    { id: 42, title: "Saved", content: "Saved prompt", liked: true, used_in_chat: true },
  ]);

  assert.equal(records[0]?.clientId, "prompt-initial-42");
  assert.equal(records[0]?.liked, true);
  assert.equal(records[0]?.used_in_chat, true);

  const cachedPrompt = toCachedPromptData(records)[0];
  assert.equal("clientId" in (cachedPrompt || {}), false);
  assert.equal(cachedPrompt?.id, 42);
  assert.equal(cachedPrompt?.title, "Saved");
  assert.equal(cachedPrompt?.liked, true);
  assert.equal(cachedPrompt?.used_in_chat, true);
});

test("appendUniquePromptRecords keeps cursor page order and removes duplicate IDs", () => {
  const appended = appendUniquePromptRecords(prompts.slice(0, 2), [
    { ...prompts[1]!, clientId: "prompt-2-duplicate" },
    { ...prompts[2]!, clientId: "prompt-3-new" },
  ]);

  assert.deepEqual(appended.map((prompt) => prompt.id), [1, 2, 3]);
  assert.equal(appended[1]?.clientId, "prompt-2");
});

test("buildPromptCountMeta identifies a partially loaded feed", () => {
  assert.equal(
    buildPromptCountMeta(prompts, "all", "all", "all", { hasMore: true }),
    "公開プロンプト: 3件を表示",
  );
});
